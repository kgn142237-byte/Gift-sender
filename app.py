import os
import json
import base64
import requests
import urllib3

from datetime import datetime
from flask import Flask, request, jsonify, Response
from dotenv import load_dotenv

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

from google.protobuf.json_format import MessageToDict

# =========================
# PROTO FILES
# =========================
import GetGiftStoreDetails_pb2
import GetWallet_pb2
import SendGift_pb2

# =========================
# LOAD ENV
# =========================
load_dotenv()

IMAGE_BASE_URL = os.getenv("IMAGE_BASE_URL", "")

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

# =========================
# CONFIG
# =========================
KEY = bytes([
    89, 103, 38, 116,
    99, 37, 68, 69,
    117, 104, 54, 37,
    90, 99, 94, 56
])

IV = bytes([
    54, 111, 121, 90,
    68, 114, 50, 50,
    69, 51, 121, 99,
    104, 106, 77, 37
])

USER_AGENT = "UnityPlayer/2022.3.47f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)"

STORE_CACHE = {}

# =========================
# CATEGORY MAP
# =========================
PREFIX_MAP = {
    "902": "Avatar",
    "214": "Facepaint",
    "101": "Female Skills",
    "102": "Male Skills",
    "103": "Microchip",
    "905": "Parachute",
    "710": "Bundle",
    "720": "Bundle2",
    "203": "Top",
    "204": "Bottom",
    "205": "Shoes",
    "211": "Head",
    "901": "Banner",
    "131": "Pet2",
    "130": "Pets/Emotes",
    "903": "Loot Box",
    "904": "Backpack",
    "906": "Skyboard",
    "907": "Others",
    "908": "Vehicles",
    "909": "Emote",
    "911": "SkyWings",
    "922": "Skill Skin",
}

# =========================
# ENCRYPT
# =========================
def encrypt_payload(data):

    cipher = AES.new(KEY, AES.MODE_CBC, IV)

    return cipher.encrypt(
        pad(data, AES.block_size)
    )

# =========================
# SERVER URL
# =========================
def get_server_url(region):

    if region == "IND":
        return "https://client.ind.freefiremobile.com"

    elif region in ["BR", "US", "SAC", "NA"]:
        return "https://client.us.freefiremobile.com"

    else:
        return "https://clientbp.ggpolarbear.com"

# =========================
# JWT DECODE
# =========================
def decode_jwt(token):

    try:

        payload = token.split('.')[1]

        payload += '=' * (4 - len(payload) % 4)

        decoded = json.loads(
            base64.b64decode(payload)
        )

        return (
            decoded.get("lock_region"),
            decoded.get("external_id")
        )

    except:
        return None, None

# =========================
# WALLET
# =========================
def get_wallet_data(jwt, login_token, region):

    req = GetWallet_pb2.CSGetWalletReq(
        login_token=login_token,
        topup_rebate=False
    )

    headers = {
        "Authorization": f"Bearer {jwt}",
        "X-GA": "v1 1",
        "ReleaseVersion": "OB53",
        "Content-Type": "application/octet-stream",
        "User-Agent": USER_AGENT
    }

    try:

        response = requests.post(
            f"{get_server_url(region)}/GetWallet",
            data=encrypt_payload(
                req.SerializeToString()
            ),
            headers=headers,
            verify=False,
            timeout=10
        )

        if response.status_code == 200:

            res_pb = GetWallet_pb2.CSGetWalletRes()

            res_pb.ParseFromString(response.content)

            wallet = res_pb.wallet

            return {
                "gold": wallet.coins,
                "diamond": wallet.gems
            }

    except:
        pass

    return {
        "gold": 0,
        "diamond": 0
    }

# =========================
# HOME
# =========================
@app.route('/')
def home():

    return jsonify({
        "status": "API Running"
    })

# =========================
# IMAGE API
# =========================
@app.route('/api/image/<item_id>')
def image(item_id):

    try:

        response = requests.get(
            f"{IMAGE_BASE_URL}{item_id}.png",
            timeout=5
        )

        return Response(
            response.content,
            mimetype='image/png'
        )

    except:
        return "Not Found", 404

# =========================
# GET STORE
# =========================
@app.route('/api/get_store', methods=['POST'])
def get_store():

    data = request.json

    jwt = data.get("jwt")

    page = int(data.get("page", 1))

    limit = int(data.get("limit", 24))

    category = data.get("category", "All")

    region, login_token = decode_jwt(jwt)

    if not region:

        return jsonify({
            "success": False,
            "message": "Invalid JWT"
        })

    if jwt not in STORE_CACHE:

        wallet = get_wallet_data(
            jwt,
            login_token,
            region
        )

        req_pb = GetGiftStoreDetails_pb2.CSGetGiftStoreDetailsReq(
            store_id=1
        )

        headers = {
            "Authorization": f"Bearer {jwt}",
            "X-GA": "v1 1",
            "ReleaseVersion": "OB53",
            "Content-Type": "application/octet-stream",
            "User-Agent": USER_AGENT
        }

        response = requests.post(
            f"{get_server_url(region)}/GetGiftStoreDetails",
            data=encrypt_payload(
                req_pb.SerializeToString()
            ),
            headers=headers,
            verify=False,
            timeout=15
        )

        if response.status_code != 200:

            return jsonify({
                "success": False,
                "message": "Garena Error"
            })

        res_pb = GetGiftStoreDetails_pb2.CSGetGiftStoreDetailsRes()

        res_pb.ParseFromString(response.content)

        res_dict = MessageToDict(
            res_pb,
            preserving_proto_field_name=True,
            always_print_fields_with_no_presence=True
        )

        items = []

        categories = set()

        for item in res_dict.get("items", []):

            item_id = str(item.get("item_id", "0"))

            category_name = PREFIX_MAP.get(
                item_id[:3],
                f"Other ({item_id[:3]})"
            )

            categories.add(category_name)

            items.append({
                "item_id": item_id,
                "commodity_id": item.get("commodity_id"),
                "gems_price": item.get("gems_price", 0),
                "coins_price": item.get("coins_price", 0),
                "category": category_name
            })

        STORE_CACHE[jwt] = {
            "items": items,
            "categories": sorted(list(categories)),
            "wallet": wallet
        }

    cache = STORE_CACHE[jwt]

    filtered = (
        [x for x in cache["items"] if x["category"] == category]
        if category != "All"
        else cache["items"]
    )

    start = (page - 1) * limit

    return jsonify({
        "success": True,
        "wallet": cache["wallet"],
        "categories": cache["categories"],
        "items": filtered[start:start + limit]
    })

# =========================
# SEND SINGLE GIFT
# =========================
@app.route('/api/send_gift/<jwt>/<uid>/<item_id>', methods=['GET'])
def send_gift_direct(jwt, uid, item_id):

    region, _ = decode_jwt(jwt)

    if not region:
        return jsonify({
            "success": False,
            "message": "Invalid JWT"
        })

    req = SendGift_pb2.CSSendGiftReq()

    req.receiver_account_ids.append(int(uid))

    req.buddy_type = 1

    req.commodity_id = int(item_id)

    req.message_content = "Gift"

    req.currency_type = 2

    req.commodity_cnt = 1

    req.unit_price = 1

    headers = {
        "Authorization": f"Bearer {jwt}",
        "X-GA": "v1 1",
        "ReleaseVersion": "OB53",
        "Content-Type": "application/octet-stream",
        "User-Agent": USER_AGENT
    }

    try:

        response = requests.post(
            f"{get_server_url(region)}/SendGift",
            data=encrypt_payload(
                req.SerializeToString()
            ),
            headers=headers,
            verify=False,
            timeout=15
        )

        if response.status_code == 200:

            return jsonify({
                "success": True,
                "message": f"Gift Sent To {uid}"
            })

        return jsonify({
            "success": False,
            "message": response.text
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "message": str(e)
        })

    req = SendGift_pb2.CSSendGiftReq()

    req.receiver_account_ids.append(int(uid))

    req.buddy_type = 1

    req.commodity_id = int(commodity_id)

    req.message_content = message

    req.currency_type = 2 if currency == "diamond" else 1

    req.commodity_cnt = 1

    req.unit_price = int(price)

    headers = {
        "Authorization": f"Bearer {jwt}",
        "X-GA": "v1 1",
        "ReleaseVersion": "OB53",
        "Content-Type": "application/octet-stream",
        "User-Agent": USER_AGENT
    }

    response = requests.post(
        f"{get_server_url(region)}/SendGift",
        data=encrypt_payload(
            req.SerializeToString()
        ),
        headers=headers,
        verify=False,
        timeout=15
    )

    if response.status_code == 200:

        return jsonify({
            "success": True,
            "message": "Gift Sent Successfully"
        })

    return jsonify({
        "success": False,
        "message": response.text
    })

# =========================
# ONE CLICK SEND ALL
# =========================
@app.route('/api/send_all_gift', methods=['POST'])
def send_all_gift():

    data = request.json

    jwt = data.get("jwt")

    uid = data.get("uid")

    item_ids = data.get("item_ids")

    message = data.get("message", "Gift")

    region, _ = decode_jwt(jwt)

    if not region:

        return jsonify({
            "success": False,
            "message": "Invalid JWT"
        })

    headers = {
        "Authorization": f"Bearer {jwt}",
        "X-GA": "v1 1",
        "ReleaseVersion": "OB53",
        "Content-Type": "application/octet-stream",
        "User-Agent": USER_AGENT
    }

    sent = []

    failed = []

    ids = item_ids.split(",")

    for item in ids:

        item = item.strip()

        try:

            req = SendGift_pb2.CSSendGiftReq()

            req.receiver_account_ids.append(
                int(uid)
            )

            req.buddy_type = 1

            req.commodity_id = int(item)

            req.message_content = message

            req.currency_type = 2

            req.commodity_cnt = 1

            req.unit_price = 1

            response = requests.post(
                f"{get_server_url(region)}/SendGift",
                data=encrypt_payload(
                    req.SerializeToString()
                ),
                headers=headers,
                verify=False,
                timeout=15
            )

            if response.status_code == 200:

                sent.append(item)

            else:

                failed.append(item)

        except Exception as e:

            failed.append({
                item: str(e)
            })

    return jsonify({
        "success": True,
        "total_sent": len(sent),
        "total_failed": len(failed),
        "sent_items": sent,
        "failed_items": failed
    })

# =========================
# RUN
# =========================
if __name__ == '__main__':

    app.run(
        host='0.0.0.0',
        port=8080,
        debug=True
    )
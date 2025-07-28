from flask import Flask, request, jsonify
import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode
import os

app = Flask(__name__)

BASE_URL = "https://open-api.bingx.com"
FIREBASE_URL = os.getenv("FIREBASE_URL")


def generate_signature(params: dict, secret: str):
    query_string = urlencode(sorted(params.items()))
    signature = hmac.new(secret.encode(), query_string.encode(), hashlib.sha256).hexdigest()
    return signature, query_string


def place_swap_market_order(symbol, side, quantity, api_key, secret_key):
    path = "/openApi/swap/v2/trade/order"
    url = BASE_URL + path
    timestamp = int(time.time() * 1000)

    swap_side = "OPEN_LONG" if side == "BUY" else "OPEN_SHORT"

    if float(quantity) <= 0:
        return {"error": "Volumen darf nicht 0 sein"}, {}, ""

    params = {
        "symbol": symbol,
        "side": swap_side,
        "type": "MARKET",
        "price": "",
        "vol": str(quantity),
        "leverage": "1",
        "timestamp": timestamp
    }

    signature, _ = generate_signature(params, secret_key)
    params["sign"] = signature

    headers = {
        "X-BX-APIKEY": api_key,
        "Content-Type": "application/x-www-form-urlencoded"
    }

    body = urlencode(params)
    response = requests.post(url, headers=headers, data=body)

    try:
        return response.json(), params, response.text
    except:
        return {"error": "Antwort kein JSON"}, params, response.text


def get_swap_position_volume(symbol, api_key, secret_key):
    path = "/openApi/swap/v2/user/positions"
    url = BASE_URL + path
    timestamp = int(time.time() * 1000)

    params = {"timestamp": timestamp}
    signature, _ = generate_signature(params, secret_key)
    params["sign"] = signature

    headers = {"X-BX-APIKEY": api_key}
    response = requests.get(url, headers=headers, params=params)
    try:
        data = response.json()
    except:
        return 0.0, {}

    for pos in data.get("data", []):
        if pos.get("symbol") == symbol and pos.get("holdSide") == "LONG":
            return float(pos.get("volume", 0)), data

    return 0.0, data


def place_swap_limit_close_order(symbol, quantity, price, api_key, secret_key):
    path = "/openApi/swap/v2/trade/order"
    url = BASE_URL + path
    timestamp = int(time.time() * 1000)

    params = {
        "symbol": symbol,
        "side": "CLOSE_LONG",
        "type": "LIMIT",
        "price": str(price),
        "vol": str(quantity),
        "leverage": "1",
        "timestamp": timestamp
    }

    signature, _ = generate_signature(params, secret_key)
    params["sign"] = signature

    headers = {
        "X-BX-APIKEY": api_key,
        "Content-Type": "application/x-www-form-urlencoded"
    }

    body = urlencode(params)
    response = requests.post(url, headers=headers, data=body)

    try:
        return response.json(), params, response.text
    except:
        return {"error": "Antwort kein JSON"}, params, response.text


def cancel_all_swap_orders(symbol, api_key, secret_key):
    path = "/openApi/swap/v2/trade/order/cancelAll"
    url = BASE_URL + path
    timestamp = int(time.time() * 1000)
    params = {"symbol": symbol, "timestamp": timestamp}

    signature, _ = generate_signature(params, secret_key)
    params["sign"] = signature

    headers = {
        "X-BX-APIKEY": api_key,
        "Content-Type": "application/x-www-form-urlencoded"
    }

    body = urlencode(params)
    response = requests.post(url, headers=headers, data=body)

    try:
        return response.json()
    except:
        return {"error": "Antwort kein JSON", "content": response.text}


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    if not data:
        return jsonify({"error": "No JSON received"}), 400

    symbol_raw = data.get("symbol")
    symbol = symbol_raw.replace("/", "-").upper()
    side = data.get("side", "BUY").upper()
    usdt_amount = float(data.get("usdt_amount", 0))
    price = float(data.get("price", 0))
    limit_percent = float(data.get("limit_sell_percent", 0))
    api_key = data.get("BINGX_API_KEY")
    secret_key = data.get("BINGX_SECRET_KEY")
    firebase_secret = data.get("firebase_secret")

    # Get live market price
    try:
        mark_price_resp = requests.get(f"{BASE_URL}/openApi/swap/v2/quote/price", params={"symbol": symbol})
        price_data = mark_price_resp.json()
        market_price = float(price_data["data"]["price"])
    except:
        return jsonify({"error": "Konnte Marktpreis nicht abrufen"}), 400

    if market_price <= 0:
        return jsonify({"error": "Ungültiger Marktpreis"}), 400

    vol = round(usdt_amount / market_price, 6)
    if vol <= 0:
        return jsonify({"error": "Berechnetes Volumen ist 0"}), 400

    firebase_response = {}
    if FIREBASE_URL and firebase_secret:
        firebase_path = f"{FIREBASE_URL}/kaufpreise/{symbol.replace('-', '')}.json?auth={firebase_secret}"
        firebase_data = {"price": price}
        try:
            firebase_post = requests.post(firebase_path, json=firebase_data)
            firebase_response = firebase_post.json()
        except:
            firebase_response = {"error": "Firebase Antwort kein JSON"}

    market_resp, market_params, market_raw = place_swap_market_order(symbol, side, vol, api_key, secret_key)

    time.sleep(2)
    position_volume, position_raw = get_swap_position_volume(symbol, api_key, secret_key)

    target_price = round(price * (1 + limit_percent / 100), 2)

    cancel_result = cancel_all_swap_orders(symbol, api_key, secret_key)

    limit_resp = {}
    limit_params = {}
    limit_raw = ""
    if position_volume > 0:
        limit_resp, limit_params, limit_raw = place_swap_limit_close_order(symbol, position_volume, target_price, api_key, secret_key)

    return jsonify({
        "symbol": symbol,
        "market_order_response": market_resp,
        "market_order_params": market_params,
        "market_order_raw": market_raw,
        "position_size": position_volume,
        "position_raw": position_raw,
        "target_price": target_price,
        "limit_order_response": limit_resp,
        "limit_order_params": limit_params,
        "limit_order_raw": limit_raw,
        "cancel_open_orders_result": cancel_result,
        "firebase_response": firebase_response
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

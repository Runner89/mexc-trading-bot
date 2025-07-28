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

    params = {
        "symbol": symbol,
        "side": swap_side,
        "type": "MARKET",
        "price": "",  # leer für Market
        "vol": str(quantity),
        "leverage": "1",
        "timestamp": timestamp
    }

    signature, query_string = generate_signature(params, secret_key)
    params["sign"] = signature

    headers = {
        "X-BX-APIKEY": api_key,
        "Content-Type": "application/x-www-form-urlencoded"
    }

    response = requests.post(url, headers=headers, data=params)
    try:
        return response.json(), params, response.text
    except:
        return {"error": "Antwort kein JSON"}, params, response.text

def cancel_all_swap_orders(symbol, api_key, secret_key):
    path = "/openApi/swap/v2/trade/allOpenOrders"
    url = BASE_URL + path
    timestamp = int(time.time() * 1000)

    params = {
        "symbol": symbol,
        "timestamp": timestamp
    }

    signature, _ = generate_signature(params, secret_key)
    params["sign"] = signature
    headers = {"X-BX-APIKEY": api_key}

    response = requests.post(url, headers=headers, data=params)
    try:
        return response.json()
    except:
        return {"error": "Fehler beim Löschen offener Orders"}

def place_swap_limit_close_order(symbol, side, quantity, price, api_key, secret_key):
    path = "/openApi/swap/v2/trade/order"
    url = BASE_URL + path
    timestamp = int(time.time() * 1000)

    close_side = "CLOSE_LONG" if side == "BUY" else "CLOSE_SHORT"

    params = {
        "symbol": symbol,
        "side": close_side,
        "type": "LIMIT",
        "price": str(price),
        "vol": str(quantity),
        "leverage": "1",
        "timestamp": timestamp
    }

    signature, _ = generate_signature(params, secret_key)
    params["sign"] = signature

    headers = {"X-BX-APIKEY": api_key, "Content-Type": "application/x-www-form-urlencoded"}
    response = requests.post(url, headers=headers, data=params)
    try:
        return response.json(), params, response.text
    except:
        return {"error": "Limit Order fehlgeschlagen"}, params, response.text

def get_swap_position(symbol, api_key, secret_key):
    path = "/openApi/swap/v2/user/positions"
    url = BASE_URL + path
    timestamp = int(time.time() * 1000)
    params = {"timestamp": timestamp}
    signature, _ = generate_signature(params, secret_key)
    params["sign"] = signature
    headers = {"X-BX-APIKEY": api_key}
    try:
        response = requests.get(url, headers=headers, params=params)
        data = response.json().get("data", [])
        for pos in data:
            if pos.get("symbol") == symbol:
                return float(pos.get("positionAmount", 0)), data
    except:
        return 0.0, {}
    return 0.0, {}

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    if not data:
        return jsonify({"error": "Kein JSON erhalten"}), 400

    symbol = data["symbol"].upper()
    side = data["side"].upper()
    usdt_amount = float(data["usdt_amount"])
    api_key = data["BINGX_API_KEY"]
    secret_key = data["BINGX_SECRET_KEY"]
    entry_price = float(data.get("price", 0))
    firebase_secret = data.get("firebase_secret")
    limit_percent = float(data.get("limit_sell_percent", 0))

    quantity = round(usdt_amount / entry_price, 6) if entry_price > 0 else 0

    # 1. Market Entry
    market_resp, market_params, market_raw = place_swap_market_order(
        symbol, side, quantity, api_key, secret_key
    )

    # 2. Firebase
    firebase_resp = {}
    if firebase_secret and entry_price > 0:
        firebase_url = f"{FIREBASE_URL}/futures/{symbol}.json?auth={firebase_secret}"
        firebase_push = requests.post(firebase_url, json={"price": entry_price})
        try:
            firebase_resp = firebase_push.json()
        except:
            firebase_resp = {"error": "Firebase Fehler"}

    # 3. Gewinnziel
    target_price = round(entry_price * (1 + limit_percent / 100), 6)

    # 4. Offene Orders löschen
    cancel_result = cancel_all_swap_orders(symbol, api_key, secret_key)

    # 5. Position holen
    pos_size, position_raw = get_swap_position(symbol, api_key, secret_key)

    # 6. Limit-Order zum Schließen setzen
    limit_resp, limit_params, limit_raw = {}, {}, ""
    if pos_size > 0:
        limit_resp, limit_params, limit_raw = place_swap_limit_close_order(
            symbol, side, pos_size, target_price, api_key, secret_key
        )

    return jsonify({
        "symbol": symbol,
        "market_order_response": market_resp,
        "market_order_params": market_params,
        "market_order_raw": market_raw,
        "firebase_response": firebase_resp,
        "target_price": target_price,
        "cancel_open_orders_result": cancel_result,
        "position_size": pos_size,
        "position_raw": position_raw,
        "limit_order_response": limit_resp,
        "limit_order_params": limit_params,
        "limit_order_raw": limit_raw
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

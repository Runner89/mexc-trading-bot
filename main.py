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

def place_futures_market_order(symbol, side, quantity, api_key, secret_key):
    path = "/openApi/futures/v1/contract/order"
    url = BASE_URL + path
    timestamp = int(time.time() * 1000)

    params = {
        "symbol": symbol,
        "price": "0",  # Marktorder
        "vol": str(quantity),
        "side": 1 if side == "BUY" else 2,
        "type": 2,  # 2 = Market
        "open_type": 1,  # 1 = isolated
        "position_id": 0,
        "leverage": 1,
        "external_oid": f"oid_{timestamp}",
        "position_mode": 1,
        "timestamp": timestamp
    }

    signature, query_string = generate_signature(params, secret_key)
    params["sign"] = signature
    headers = {"X-BX-APIKEY": api_key}
    response = requests.post(url, headers=headers, data=params)
    try:
        return response.json(), params, response.text
    except Exception:
        return {"error": "Antwort kein JSON"}, params, response.text

def cancel_all_futures_orders(symbol, api_key, secret_key):
    path = "/openApi/futures/v1/contract/cancel-all"
    url = BASE_URL + path
    timestamp = int(time.time() * 1000)
    params = {
        "symbol": symbol,
        "timestamp": timestamp
    }
    signature, query_string = generate_signature(params, secret_key)
    params["sign"] = signature
    headers = {"X-BX-APIKEY": api_key}
    response = requests.post(url, headers=headers, data=params)
    try:
        return response.json()
    except:
        return {"error": "Fehler beim Stornieren"}

def place_futures_limit_order(symbol, side, quantity, price, api_key, secret_key):
    path = "/openApi/futures/v1/contract/order"
    url = BASE_URL + path
    timestamp = int(time.time() * 1000)

    params = {
        "symbol": symbol,
        "price": str(price),
        "vol": str(quantity),
        "side": side,  # 3 = Buy Close Short, 4 = Sell Close Long
        "type": 1,  # 1 = Limit
        "open_type": 1,
        "position_id": 0,
        "leverage": 1,
        "external_oid": f"limit_{timestamp}",
        "position_mode": 1,
        "timestamp": timestamp
    }

    signature, query_string = generate_signature(params, secret_key)
    params["sign"] = signature
    headers = {"X-BX-APIKEY": api_key}
    response = requests.post(url, headers=headers, data=params)
    try:
        return response.json(), params, response.text
    except:
        return {"error": "Limit Order fehlgeschlagen"}, params, response.text

def get_futures_position(symbol, api_key, secret_key):
    path = "/openApi/futures/v1/contract/positions"
    url = BASE_URL + path
    timestamp = int(time.time() * 1000)

    params = {
        "symbol": symbol,
        "timestamp": timestamp
    }
    signature, query_string = generate_signature(params, secret_key)
    params["sign"] = signature
    headers = {"X-BX-APIKEY": api_key}

    response = requests.get(url, headers=headers, params=params)
    try:
        raw = response.json()
        positions = raw.get("data", [])
        for pos in positions:
            if pos.get("symbol") == symbol:
                return float(pos.get("availableVol", 0)), raw
    except:
        return 0.0, {}
    return 0.0, {}

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    if not data:
        return jsonify({"error": "Kein JSON erhalten"}), 400

    symbol_raw = data["symbol"].upper()
    side = data["side"].upper()
    usdt_amount = float(data["usdt_amount"])
    api_key = data["BINGX_API_KEY"]
    secret_key = data["BINGX_SECRET_KEY"]
    price = float(data.get("price", 0))
    firebase_secret = data.get("firebase_secret")
    limit_sell_percent = float(data.get("limit_sell_percent", 0))

    qty = usdt_amount / price if price else 0

    market_order_resp, market_params, market_text = place_futures_market_order(
        symbol_raw, side, qty, api_key, secret_key
    )

    avg_price = price
    firebase_resp = {}
    firebase_write = {}

    if firebase_secret and price > 0:
        fb_path = f"{FIREBASE_URL}/futures/{symbol_raw}.json?auth={firebase_secret}"
        firebase_write = requests.post(fb_path, json={"price": price})
        try:
            firebase_resp = firebase_write.json()
        except:
            firebase_resp = {"error": "Firebase-Antwort kein JSON"}

    # Neue Verkaufspreis mit Gewinn
    sell_price = round(avg_price * (1 + limit_sell_percent / 100), 6)
    cancel_result = cancel_all_futures_orders(symbol_raw, api_key, secret_key)
    pos_size, raw_pos = get_futures_position(symbol_raw, api_key, secret_key)

    close_side = 4 if side == "BUY" else 3  # 4 = close long, 3 = close short
    limit_resp, limit_params, limit_text = {}, {}, ""

    if pos_size > 0:
        limit_resp, limit_params, limit_text = place_futures_limit_order(
            symbol_raw, close_side, pos_size, sell_price, api_key, secret_key
        )

    return jsonify({
        "symbol": symbol_raw,
        "market_order_response": market_order_resp,
        "market_order_params": market_params,
        "market_order_raw": market_text,
        "firebase_response": firebase_resp,
        "limit_sell_price": sell_price,
        "cancel_open_orders_result": cancel_result,
        "position_volume": pos_size,
        "position_raw": raw_pos,
        "limit_order_response": limit_resp,
        "limit_order_params": limit_params,
        "limit_order_raw": limit_text
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

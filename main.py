from flask import Flask, request, jsonify
import time
import hmac
import hashlib
from urllib.parse import urlencode
import requests
import os

app = Flask(__name__)

BASE_URL = "https://open-api.bingx.com/futures"
FIREBASE_URL = os.getenv("FIREBASE_URL")

def generate_signature(params: dict, secret: str) -> str:
    sorted_params = sorted(params.items())
    query_string = urlencode(sorted_params)
    signature = hmac.new(secret.encode(), query_string.encode(), hashlib.sha256).hexdigest()
    return signature

def place_futures_order(symbol, vol, side, leverage, api_key, secret_key):
    path = "/api/v1/private/order/place"
    url = BASE_URL + path
    timestamp = int(time.time() * 1000)

    params = {
        "symbol": symbol,
        "vol": str(vol),
        "side": side,  # "OPEN_LONG" oder "OPEN_SHORT"
        "type": "MARKET",  # Market Order
        "leverage": str(leverage),
        "open_type": "1",  # 1 = isolated margin
        "position_id": "0",
        "timestamp": timestamp
    }

    sign = generate_signature(params, secret_key)
    params["sign"] = sign

    headers = {
        "X-BX-APIKEY": api_key,
        "Content-Type": "application/x-www-form-urlencoded"
    }

    response = requests.post(url, headers=headers, data=params)
    try:
        return response.json()
    except:
        return {"error": "Response is not JSON", "content": response.text}

def cancel_all_futures_orders(symbol, api_key, secret_key):
    # Futures offene Orders abrufen
    path = "/api/v1/private/order/openOrders"
    url = BASE_URL + path
    timestamp = int(time.time() * 1000)
    params = {
        "symbol": symbol,
        "timestamp": timestamp
    }
    sign = generate_signature(params, secret_key)
    params["sign"] = sign
    headers = {
        "X-BX-APIKEY": api_key
    }
    resp = requests.get(url, headers=headers, params=params)
    try:
        data = resp.json()
    except:
        return {"error": "Response is not JSON", "content": resp.text}

    cancel_results = []
    if data.get("code") == 0 and "data" in data:
        for order in data["data"]:
            order_id = order.get("orderId")
            if order_id:
                cancel_result = cancel_futures_order(order_id, symbol, api_key, secret_key)
                cancel_results.append(cancel_result)
    return cancel_results

def cancel_futures_order(order_id, symbol, api_key, secret_key):
    path = "/api/v1/private/order/cancel"
    url = BASE_URL + path
    timestamp = int(time.time() * 1000)
    params = {
        "orderId": order_id,
        "symbol": symbol,
        "timestamp": timestamp
    }
    sign = generate_signature(params, secret_key)
    params["sign"] = sign
    headers = {
        "X-BX-APIKEY": api_key,
        "Content-Type": "application/x-www-form-urlencoded"
    }
    resp = requests.post(url, headers=headers, data=params)
    try:
        return resp.json()
    except:
        return {"error": "Response is not JSON", "content": resp.text}

def place_limit_sell_order(symbol, vol, price, api_key, secret_key):
    path = "/api/v1/private/order/place"
    url = BASE_URL + path
    timestamp = int(time.time() * 1000)

    params = {
        "symbol": symbol,
        "vol": str(vol),
        "side": "CLOSE_SHORT",  # Verkaufen Long-Position oder schliessen Short-Position
        "type": "LIMIT",
        "price": str(price),
        "leverage": "1",
        "open_type": "1",
        "position_id": "0",
        "timestamp": timestamp,
        "reduce_only": "true"  # Nur Position reduzieren (verkaufen)
    }

    sign = generate_signature(params, secret_key)
    params["sign"] = sign

    headers = {
        "X-BX-APIKEY": api_key,
        "Content-Type": "application/x-www-form-urlencoded"
    }

    resp = requests.post(url, headers=headers, data=params)
    try:
        return resp.json()
    except:
        return {"error": "Response is not JSON", "content": resp.text}

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    if not data:
        return jsonify({"error": "Kein JSON erhalten"}), 400

    symbol_raw = data.get("symbol")  # z.B. "BTC-USDT"
    if not symbol_raw:
        return jsonify({"error": "symbol fehlt"}), 400

    side = data.get("side", "OPEN_LONG").upper()  # OPEN_LONG oder OPEN_SHORT
    vol = data.get("vol")  # Menge als float oder string
    if vol is None:
        return jsonify({"error": "vol fehlt"}), 400

    leverage = data.get("leverage", 1)
    api_key = data.get("BINGX_API_KEY")
    secret_key = data.get("BINGX_SECRET_KEY")
    if not api_key or not secret_key:
        return jsonify({"error": "API Schlüssel fehlen"}), 400

    price = data.get("price")  # Optional für Limit-Verkauf
    limit_sell_percent = data.get("limit_sell_percent")  # z.B. 5 für +5% Verkauf
    firebase_secret = data.get("firebase_secret")

    # 1. Offene Futures-Orders stornieren
    cancel_results = cancel_all_futures_orders(symbol_raw, api_key, secret_key)

    # 2. Market Order platzieren
    order_result = place_futures_order(symbol_raw, vol, side, leverage, api_key, secret_key)

    # 3. Optional: Firebase speichern
    firebase_response = None
    avg_price = None
    if firebase_secret and price is not None:
        try:
            firebase_path = f"{FIREBASE_URL}/kaufpreise/{symbol_raw.replace('-', '')}.json?auth={firebase_secret}"
            firebase_data = {"price": price}
            firebase_response = requests.post(firebase_path, json=firebase_data)
            firebase_response = firebase_response.json()

            get_prices_path = f"{FIREBASE_URL}/kaufpreise/{symbol_raw.replace('-', '')}.json?auth={firebase_secret}"
            get_response = requests.get(get_prices_path)
            all_prices_data = get_response.json()

            prices_list = [float(v.get("price")) for v in all_prices_data.values() if "price" in v]
            if prices_list:
                avg_price = sum(prices_list) / len(prices_list)
        except Exception as e:
            firebase_response = {"error": str(e)}

    # 4. Optional: Limit-Verkaufsorder platzieren
    limit_order_response = None
    limit_sell_price = None
    if avg_price and limit_sell_percent:
        limit_sell_price = round(avg_price * (1 + float(limit_sell_percent) / 100), 6)
        # Limit Sell Order, "CLOSE_LONG" schließt Long Position, "CLOSE_SHORT" schließt Short Position
        limit_order_response = place_limit_sell_order(symbol_raw, vol, limit_sell_price, api_key, secret_key)

    return jsonify({
        "symbol_raw": symbol_raw,
        "cancel_open_orders_result": cancel_results,
        "market_order_params": {
            "symbol": symbol_raw,
            "vol": vol,
            "side": side,
            "leverage": leverage
        },
        "market_order_response": order_result,
        "firebase_response": firebase_response,
        "limit_sell_price": limit_sell_price,
        "limit_order_response": limit_order_response
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

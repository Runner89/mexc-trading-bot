from flask import Flask, request, jsonify
import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode

app = Flask(__name__)

BASE_URL = "https://open-api.bingx.com"

def generate_signature(params: dict, secret: str):
    query_string = urlencode(sorted(params.items()))
    signature = hmac.new(secret.encode(), query_string.encode(), hashlib.sha256).hexdigest()
    return signature

def place_futures_market_order(symbol, side, quantity, api_key, secret_key):
    path = "/futuresApi/v1/order/placeOrder"  # Pfad für Futures Order (bitte bei BingX-Doku prüfen)
    url = BASE_URL + path
    timestamp = int(time.time() * 1000)

    params = {
        "symbol": symbol,
        "side": side,       # "BUY" oder "SELL"
        "type": "MARKET",   # Market Order
        "quantity": quantity,
        "timestamp": timestamp
    }
    signature = generate_signature(params, secret_key)
    params["signature"] = signature

    headers = {
        "X-BX-APIKEY": api_key,
        "Content-Type": "application/x-www-form-urlencoded"
    }

    response = requests.post(url, headers=headers, data=params)
    try:
        return response.json(), response.status_code
    except Exception:
        return {"error": "Antwort kein JSON", "content": response.text}, response.status_code

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    if not data:
        return jsonify({"error": "Kein JSON erhalten"}), 400

    symbol = data.get("symbol", "").upper()        # z.B. "BTCUSDTM"
    side = data.get("side", "").upper()            # "BUY"
    quantity = data.get("quantity")                 # z.B. "0.01"
    api_key = data.get("BINGX_API_KEY")
    secret_key = data.get("BINGX_SECRET_KEY")

    if not all([symbol, side, quantity, api_key, secret_key]):
        return jsonify({"error": "Fehlende Parameter"}), 400

    order_response, status_code = place_futures_market_order(symbol, side, quantity, api_key, secret_key)

    return jsonify({
        "symbol": symbol,
        "side": side,
        "quantity": quantity,
        "order_response": order_response,
        "status_code": status_code
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

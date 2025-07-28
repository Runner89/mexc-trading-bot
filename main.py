from flask import Flask, request, jsonify
import time
import hmac
import hashlib
from urllib.parse import urlencode
import requests

app = Flask(__name__)

BASE_URL = "https://open-api.bingx.com"
FUTURES_PATH = "/futuresApi/v1/order/placeOrder"

def generate_signature(params: dict, secret: str):
    query_string = urlencode(sorted(params.items()))
    signature = hmac.new(secret.encode(), query_string.encode(), hashlib.sha256).hexdigest()
    return signature

def place_futures_market_order(symbol, side, quantity, api_key, secret_key):
    url = BASE_URL + FUTURES_PATH
    timestamp = int(time.time() * 1000)

    params = {
        "symbol": symbol,
        "side": side,          # "BUY" or "SELL"
        "type": "MARKET",
        "quantity": quantity,
        "timestamp": timestamp
    }

    # Signatur mit sortierten params
    signature = generate_signature(params, secret_key)
    params["signature"] = signature

    headers = {
        "X-BX-APIKEY": api_key,
        "Content-Type": "application/x-www-form-urlencoded"
    }

    # POST-Request mit form-data
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

    symbol = data.get("symbol", "").upper()
    side = data.get("side", "").upper()
    quantity = data.get("quantity")
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

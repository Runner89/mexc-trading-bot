import os
import time
import hmac
import hashlib
import json
import requests
from flask import Flask, request, jsonify, abort



app = Flask(__name__)

API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
BASE_URL = "https://api.mexc.com"

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")

def sign_request(params, secret):
    query_string = '&'.join([f"{k}={v}" for k, v in sorted(params.items())])
    signature = hmac.new(secret.encode(), query_string.encode(), hashlib.sha256).hexdigest()
    return signature

def place_market_order(symbol, side, usdt_amount):
    price = get_market_price(symbol)
    if not price:
        return {"error": "Preis konnte nicht ermittelt werden."}
    
    quantity = round(usdt_amount / price, 4)

    params = {
        "symbol": symbol,
        "side": side.upper(),
        "type": "MARKET",
        "quantity": quantity,
        "timestamp": int(time.time() * 1000),
    }
    params["signature"] = sign_request(params, API_SECRET)

    headers = {"X-MEXC-APIKEY": API_KEY}
    response = requests.post(f"{BASE_URL}/api/v3/order", params=params, headers=headers)

    return response.json()

def get_market_price(symbol):
    try:
        url = f"{BASE_URL}/api/v3/ticker/price?symbol={symbol}"
        response = requests.get(url)
        data = response.json()
        return float(data["price"])
    except Exception:
        return None

@app.route("/webhook", methods=["POST"])
def webhook():
    secret = request.headers.get("X-Webhook-Secret")
    if secret != WEBHOOK_SECRET:
        abort(403)  # Zugriff verweigert

    data = request.json
    symbol = data.get("symbol")
    side = data.get("side")
    usdt_amount = float(data.get("usdt_amount", 10))

    if not symbol or not side:
        return jsonify({"error": "symbol und side erforderlich"}), 400

    result = place_market_order(symbol, side, usdt_amount)
    return jsonify(result)
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

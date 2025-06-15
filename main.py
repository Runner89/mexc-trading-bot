from flask import Flask, request
import os
import time
import hmac
import hashlib
import requests

app = Flask(__name__)

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()

    symbol = data.get("symbol")
    action = data.get("action")  # BUY or SELL
    quantity = data.get("quantity")
    if not all([symbol, action, quantity]):
        return "Invalid data", 400

    timestamp = int(time.time() * 1000)
    query = f"symbol={symbol}&side={action}&type=MARKET&quantity={quantity}&timestamp={timestamp}"
    secret = os.environ.get("MEXC_SECRET_KEY", "")
    api_key = os.environ.get("MEXC_API_KEY", "")
    signature = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    url = f"https://api.mexc.com/api/v3/order?{query}&signature={signature}"
    headers = {"X-MEXC-APIKEY": api_key}

    try:
        response = requests.post(url, headers=headers)
        return response.text, response.status_code
    except Exception as e:
        return str(e), 500

@app.route("/", methods=["GET"])
def home():
    return "✅ MEXC Python Bot läuft"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

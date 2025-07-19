#USDT Spot Kauf wird in erstellt, BINGX API + Secret Key werden mit JSON gesendet


from flask import Flask, request, jsonify
import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode

app = Flask(__name__)

BASE_URL = "https://open-api.bingx.com"

def generate_signature(params: dict, secret: str) -> str:
    # URL-kodierter Query-String, sortiert nach Keys
    query_string = urlencode(sorted(params.items()))
    print("Query String for signature:", query_string)
    signature = hmac.new(secret.encode(), query_string.encode(), hashlib.sha256).hexdigest()
    print("Generated signature:", signature)
    return signature

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    if not data:
        return jsonify({"error": "Kein JSON erhalten"}), 400

    required_keys = ["symbol", "side", "usdt_amount", "BINGX_API_KEY", "BINGX_SECRET_KEY"]
    missing = [k for k in required_keys if k not in data]
    if missing:
        return jsonify({"error": f"Fehlende Felder: {missing}"}), 400

    symbol = data["symbol"]
    side = data["side"].upper()
    amount = str(data["usdt_amount"])  # Wichtig: als String
    api_key = data["BINGX_API_KEY"]
    secret_key = data["BINGX_SECRET_KEY"]

    path = "/openApi/spot/v1/trade/order"
    url = BASE_URL + path
    timestamp = int(time.time() * 1000)

    params = {
        "quoteOrderQty": amount,
        "side": side,
        "symbol": symbol,
        "timestamp": timestamp,
        "type": "MARKET"
    }

    signature = generate_signature(params, secret_key)
    params["signature"] = signature

    headers = {
        "X-BX-APIKEY": api_key,
        "Content-Type": "application/x-www-form-urlencoded"
    }

    response = requests.post(url, headers=headers, data=params)

    try:
        resp_json = response.json()
    except Exception:
        resp_json = {"error": "Antwort kein JSON", "content": response.text}

    return jsonify({
        "status_code": response.status_code,
        "response": resp_json
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

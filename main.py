from flask import Flask, request, jsonify
import time
import hmac
import hashlib
import requests

app = Flask(__name__)

BASE_URL = "https://open-api.bingx.com"

def generate_signature(params: dict, secret: str) -> str:
    query_string = '&'.join(f"{key}={params[key]}" for key in sorted(params))
    return hmac.new(secret.encode(), query_string.encode(), hashlib.sha256).hexdigest()

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    if not data:
        return jsonify({"error": "No JSON received"}), 400

    required_keys = ["symbol", "side", "usdt_amount", "BINGX_API_KEY", "BINGX_SECRET_KEY"]
    if not all(k in data for k in required_keys):
        return jsonify({"error": f"Missing one of required keys: {required_keys}"}), 400

    symbol = data["symbol"]
    side = data["side"]
    amount = data["usdt_amount"]
    api_key = data["BINGX_API_KEY"]
    secret_key = data["BINGX_SECRET_KEY"]

    path = "/openApi/spot/v1/trade/order"
    url = BASE_URL + path
    timestamp = str(int(time.time() * 1000))

    params = {
        "symbol": symbol,
        "side": side,
        "type": "MARKET",
        "quoteOrderQty": amount,
        "timestamp": timestamp
    }

    signature = generate_signature(params, secret_key)
    params["signature"] = signature

    headers = {
        "X-BX-APIKEY": api_key
    }

    response = requests.post(url, headers=headers, data=params)

    return jsonify({
        "status_code": response.status_code,
        "response": response.json()
    })

if __name__ == "__main__":
    # Starte den Webserver auf Port 5000
    app.run(host="0.0.0.0", port=5000)

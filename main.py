from flask import Flask, request, jsonify
import time
import hmac
import hashlib
import requests

app = Flask(__name__)

BASE_URL = "https://open-api.bingx.com"

def generate_signature(params: dict, secret: str) -> str:
    query_string = '&'.join(f"{key}={params[key]}" for key in sorted(params))
    print("Query String for signature:", query_string)
    signature = hmac.new(secret.encode(), query_string.encode(), hashlib.sha256).hexdigest()
    print("Generated signature:", signature)
    return signature

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    if not data:
        return jsonify({"error": "No JSON payload received"}), 400

    required_keys = ["symbol", "side", "usdt_amount", "BINGX_API_KEY", "BINGX_SECRET_KEY"]
    missing = [k for k in required_keys if k not in data]
    if missing:
        return jsonify({"error": f"Missing keys in JSON: {missing}"}), 400

    symbol = data["symbol"]
    side = data["side"].upper()  # Großbuchstaben wie "BUY"
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
        "quoteOrderQty": str(amount),  # als String
        "timestamp": timestamp
    }

    signature = generate_signature(params, secret_key)
    params["signature"] = signature

    headers = {
        "X-BX-APIKEY": api_key
    }

    print("Sending POST request to BingX API...")
    response = requests.post(url, headers=headers, data=params)

    print("Status:", response.status_code)
    try:
        resp_json = response.json()
        print("Response JSON:", resp_json)
    except Exception as e:
        resp_json = {"error": "Could not decode JSON from response"}
        print("Response content:", response.text)

    return jsonify({
        "status_code": response.status_code,
        "response": resp_json
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

from flask import Flask, request, jsonify
import time
import hmac
import hashlib
import requests

app = Flask(__name__)

BASE_URL = "https://open-api.bingx.com"
ENDPOINT = "/openApi/swap/v2/user/balance"

def generate_signature(secret, params):
    return hmac.new(secret.encode(), params.encode(), hashlib.sha256).hexdigest()

def get_futures_balance(api_key, secret_key):
    timestamp = int(time.time() * 1000)
    params = f"timestamp={timestamp}"
    signature = generate_signature(secret_key, params)
    url = f"{BASE_URL}{ENDPOINT}?{params}&signature={signature}"
    headers = {"X-BX-APIKEY": api_key}
    response = requests.get(url, headers=headers)
    return response.json()

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    api_key = data.get("api_key")
    secret_key = data.get("secret_key")

    if not api_key or not secret_key:
        return jsonify({"error": True, "message": "api_key and secret_key are required"}), 400

    balance_response = get_futures_balance(api_key, secret_key)
    if balance_response.get("code") == 0:
        balance_info = balance_response["data"]["balance"]
        available_margin = balance_info.get("availableMargin", "0")
        return jsonify({
            "error": False,
            "available_balance": available_margin
        })
    else:
        return jsonify({
            "error": True,
            "message": balance_response.get("msg", "Unknown error")
        }), 400

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

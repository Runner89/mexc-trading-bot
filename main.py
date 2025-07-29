from flask import Flask, request, jsonify
import time
import hmac
import hashlib
import requests

app = Flask(__name__)

BASE_URL = "https://open-api.bingx.com"
BALANCE_ENDPOINT = "/openApi/swap/v2/user/balance"
PRICE_ENDPOINT = "/openApi/swap/v2/quote/price"

def generate_signature(secret_key: str, params: str) -> str:
    return hmac.new(secret_key.encode('utf-8'), params.encode('utf-8'), hashlib.sha256).hexdigest()

def get_futures_balance(api_key: str, secret_key: str):
    timestamp = int(time.time() * 1000)
    params = f"timestamp={timestamp}"
    signature = generate_signature(secret_key, params)
    url = f"{BASE_URL}{BALANCE_ENDPOINT}?{params}&signature={signature}"
    headers = {"X-BX-APIKEY": api_key}
    response = requests.get(url, headers=headers)
    return response.json()

def measure_latency(symbol: str):
    url = f"{BASE_URL}{PRICE_ENDPOINT}?symbol={symbol}"
    start = time.time()
    response = requests.get(url)
    end = time.time()
    latency_ms = round((end - start) * 1000, 2)
    return latency_ms, response.json()

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    api_key = data.get("api_key")
    secret_key = data.get("secret_key")
    symbol = data.get("symbol", "BTC-USDT")

    if not api_key or not secret_key:
        return jsonify({"error": True, "msg": "api_key and secret_key are required"}), 400

    balance_response = get_futures_balance(api_key, secret_key)
    latency_ms, price_response = measure_latency(symbol)

    return jsonify({
        "error": False,
        "available_balances": balance_response.get("data", {}).get("balance", {}),
        "latency_ms": latency_ms,
        "price_response": price_response
    })

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)

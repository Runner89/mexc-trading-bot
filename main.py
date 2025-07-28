import time
import hmac
import hashlib
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

BASE_URL = "https://open-api.bingx.com"
BALANCE_ENDPOINT = "/openApi/swap/v2/user/balance"
ORDER_ENDPOINT = "/openApi/swap/v2/trade/order"  # Korrigiert!

def generate_signature(secret_key: str, params: str) -> str:
    return hmac.new(secret_key.encode(), params.encode(), hashlib.sha256).hexdigest()

def get_futures_balance(api_key: str, secret_key: str):
    timestamp = int(time.time() * 1000)
    params = f"timestamp={timestamp}"
    signature = generate_signature(secret_key, params)
    url = f"{BASE_URL}{BALANCE_ENDPOINT}?{params}&signature={signature}"
    headers = {"X-BX-APIKEY": api_key}
    response = requests.get(url, headers=headers)
    return response.json()

def place_market_order(api_key: str, secret_key: str, symbol: str, usdt_amount: str, position_side: str = "LONG"):
    timestamp = int(time.time() * 1000)
    # Parameter müssen URL-encoded sein, aber wir senden hier als POST x-www-form-urlencoded
    params = f"symbol={symbol}&side=BUY&type=MARKET&quoteOrderQty={usdt_amount}&positionSide={position_side}&timestamp={timestamp}"
    signature = generate_signature(secret_key, params)
    full_params = params + f"&signature={signature}"
    url = f"{BASE_URL}{ORDER_ENDPOINT}"
    headers = {
        "X-BX-APIKEY": api_key,
        "Content-Type": "application/x-www-form-urlencoded"
    }
    response = requests.post(url, headers=headers, data=full_params)
    return response.json()

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json

    api_key = data.get("api_key")
    secret_key = data.get("secret_key")

    if not api_key or not secret_key:
        return jsonify({"error": True, "message": "api_key and secret_key are required"}), 400

    # Futures Balance abrufen
    balance_response = get_futures_balance(api_key, secret_key)
    available_balances = {}
    if balance_response.get("code") == 0:
        balance_data = balance_response.get("data", {})
        balance_info = balance_data.get("balance", {})
        asset = balance_info.get("asset")
        available = balance_info.get("availableMargin")
        available_balances[asset] = available
    else:
        return jsonify({"error": True, "message": balance_response.get("msg", "Failed to get balance")})

    # Market Order falls mitgesendet
    symbol = data.get("symbol")
    usdt_amount = data.get("usdt_amount")
    position_side = data.get("positionSide", "LONG")

    order_result = None
    if symbol and usdt_amount:
        order_result = place_market_order(api_key, secret_key, symbol, str(usdt_amount), position_side)

    return jsonify({
        "error": False,
        "available_balances": available_balances,
        "order_result": order_result or "No order placed"
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

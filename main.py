from flask import Flask, request, jsonify
import time
import hmac
import hashlib
import requests

app = Flask(__name__)

BASE_URL = "https://open-api.bingx.com"
BALANCE_ENDPOINT = "/openApi/swap/v2/user/balance"
ORDER_ENDPOINT = "/openApi/swap/v2/order"  # ✅ KORRIGIERT
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

def get_current_price(symbol: str):
    url = f"{BASE_URL}/openApi/swap/v2/quote/price?symbol={symbol}"
    response = requests.get(url)
    data = response.json()
    if data.get("code") == 0 and "data" in data and "price" in data["data"]:
        return float(data["data"]["price"])
    else:
        print("❌ Price response error:", data)
        return None

def place_market_order(api_key: str, secret_key: str, symbol: str, usdt_amount: float, position_side: str = "LONG"):
    price = get_current_price(symbol)
    if price is None:
        return {"code": 99999, "msg": "Failed to get current price"}

    quantity = round(usdt_amount / price, 6)

    timestamp = int(time.time() * 1000)
    params_dict = {
        "symbol": symbol,
        "side": "BUY",
        "type": "MARKET",
        "quantity": quantity,
        "positionSide": position_side,
        "timestamp": timestamp
    }

    # Signatur String aus Params erstellen (alphabetisch sortiert)
    sign_str = "&".join(f"{k}={params_dict[k]}" for k in sorted(params_dict))
    signature = generate_signature(secret_key, sign_str)
    params_dict["signature"] = signature

    url = f"{BASE_URL}{ORDER_ENDPOINT}"
    headers = {
        "X-BX-APIKEY": api_key,
        "Content-Type": "application/x-www-form-urlencoded"
    }
    response = requests.post(url, headers=headers, data=params_dict)
    return response.json()

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    api_key = data.get("api_key")
    secret_key = data.get("secret_key")
    symbol = data.get("symbol", "BTC-USDT")
    usdt_amount = data.get("usdt_amount")
    position_side = data.get("position_side") or data.get("positionSide") or "LONG"

    if not api_key or not secret_key or not usdt_amount:
        return jsonify({"error": True, "msg": "api_key, secret_key and usdt_amount are required"}), 400

    balance_response = get_futures_balance(api_key, secret_key)
    order_response = place_market_order(api_key, secret_key, symbol, float(usdt_amount), position_side)

    return jsonify({
        "error": False,
        "available_balances": balance_response.get("data", {}).get("balance", {}),
        "order_result": order_response,
        "order_params": {
            "symbol": symbol,
            "usdt_amount": usdt_amount,
            "position_side": position_side
        }
    })

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)

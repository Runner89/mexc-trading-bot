from flask import Flask, request, jsonify
import time
import hmac
import hashlib
import requests

app = Flask(__name__)

BASE_URL = "https://open-api.bingx.com"
BALANCE_ENDPOINT = "/openApi/swap/v2/user/balance"
ORDER_ENDPOINT = "/openApi/swap/v2/trade/order"

def generate_signature(secret, params):
    return hmac.new(secret.encode(), params.encode(), hashlib.sha256).hexdigest()

def get_futures_balance(api_key, secret_key):
    timestamp = int(time.time() * 1000)
    params = f"timestamp={timestamp}"
    signature = generate_signature(secret_key, params)
    url = f"{BASE_URL}{BALANCE_ENDPOINT}?{params}&signature={signature}"
    headers = {"X-BX-APIKEY": api_key}
    response = requests.get(url, headers=headers)
    return response.json()

def place_market_order(api_key, secret_key, symbol, usdt_amount):
    timestamp = int(time.time() * 1000)
    # Beispiel Parameter: symbol=BTC-USDT, side=BUY, type=MARKET, quoteOrderQty=usdt_amount
    # quoteOrderQty gibt den USDT-Wert an, der ausgegeben wird (Kauf für diesen Betrag)
    params = f"symbol={symbol}&side=BUY&type=MARKET&quoteOrderQty={usdt_amount}&timestamp={timestamp}"
    signature = generate_signature(secret_key, params)
    url = f"{BASE_URL}{ORDER_ENDPOINT}?{params}&signature={signature}"
    headers = {"X-BX-APIKEY": api_key}
    response = requests.post(url, headers=headers)
    return response.json()

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    api_key = data.get("api_key")
    secret_key = data.get("secret_key")

    if not api_key or not secret_key:
        return jsonify({"error": True, "message": "api_key and secret_key are required"}), 400

    # Balance holen
    balance_response = get_futures_balance(api_key, secret_key)
    if balance_response.get("code") != 0:
        return jsonify({"error": True, "message": balance_response.get("msg", "Error fetching balance")}), 400

    # Verfügbare Assets auslesen
    balances = balance_response["data"].get("balanceList") or balance_response["data"].get("balances") or []
    if not isinstance(balances, list):
        balances = [balance_response["data"]["balance"]]

    available_balances = {}
    for bal in balances:
        asset = bal.get("asset")
        available = bal.get("availableMargin") or bal.get("balance") or "0"
        if asset:
            available_balances[asset] = available

    # Falls symbol und usdt_amount im Request vorhanden sind, Order platzieren
    symbol = data.get("symbol")        # z.B. "BTC-USDT"
    usdt_amount = data.get("usdt_amount")  # z.B. "100" (als String oder Zahl)

    order_result = None
    if symbol and usdt_amount:
        order_result = place_market_order(api_key, secret_key, symbol, str(usdt_amount))

    return jsonify({
        "error": False,
        "available_balances": available_balances,
        "order_result": order_result or "No order placed"
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

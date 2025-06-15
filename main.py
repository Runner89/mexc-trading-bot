from flask import Flask, request, jsonify
import requests
import time
import hmac
import hashlib

app = Flask(__name__)

API_KEY = "dein_api_key"
API_SECRET = "dein_api_secret"

BASE_URL = "https://api.mexc.com"

def sign_request(params, secret):
    query_string = "&".join([f"{k}={v}" for k, v in sorted(params.items())])
    signature = hmac.new(secret.encode(), query_string.encode(), hashlib.sha256).hexdigest()
    return signature

def get_account_info():
    timestamp = int(time.time() * 1000)
    params = {
        "timestamp": timestamp
    }
    params["signature"] = sign_request(params, API_SECRET)
    headers = {
        "X-MEXC-APIKEY": API_KEY
    }
    resp = requests.get(f"{BASE_URL}/api/v3/account", params=params, headers=headers)
    return resp.json()

def market_sell(symbol, quantity):
    timestamp = int(time.time() * 1000)
    params = {
        "symbol": symbol,
        "side": "SELL",
        "type": "MARKET",
        "quantity": quantity,
        "timestamp": timestamp
    }
    params["signature"] = sign_request(params, API_SECRET)
    headers = {
        "X-MEXC-APIKEY": API_KEY
    }
    resp = requests.post(f"{BASE_URL}/api/v3/order", params=params, headers=headers)
    return resp.json()

@app.route("/close_donkey_position", methods=["POST"])
def close_donkey_position():
    symbol = "DONKEYUSDT"
    account_info = get_account_info()
    
    if "balances" not in account_info:
        return jsonify({"error": "Konto-Info konnte nicht abgerufen werden", "details": account_info}), 500
    
    donkey_amount = 0
    for asset in account_info["balances"]:
        if asset["asset"] == "DONKEY":
            donkey_amount = float(asset["free"])
            break

    if donkey_amount <= 0:
        return jsonify({"message": "Keine DONKEY-Position zum Schließen gefunden."}), 400
    
    # Menge runden auf 2 Dezimalstellen, da baseAssetPrecision=2
    quantity = round(donkey_amount, 2)
    
    order_result = market_sell(symbol, quantity)
    return jsonify(order_result)

if __name__ == "__main__":
    app.run(port=10000)

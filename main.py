import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode
from flask import Flask, request, jsonify

app = Flask(__name__)

BASE_URL = "https://open-api.bingx.com"
API_PATH = "/openApi/swap/v2/trade/order"

def generate_signature(params: dict, secret: str) -> str:
    query_string = urlencode(sorted(params.items()))
    return hmac.new(secret.encode(), query_string.encode(), hashlib.sha256).hexdigest()

def place_market_order(symbol, side, quantity, api_key, secret_key):
    url = BASE_URL + API_PATH
    timestamp = int(time.time() * 1000)

    # Vorbereitung der Parameter
    params = {
        "symbol": symbol,
        "side": side,
        "type": "MARKET",
        "quantity": quantity,
        "timestamp": timestamp
    }

    # Signatur erzeugen
    signature = generate_signature(params, secret_key)
    params["signature"] = signature

    # Header
    headers = {
        "X-BX-APIKEY": api_key,
        "Content-Type": "application/x-www-form-urlencoded"
    }

    # Request senden
    response = requests.post(url, headers=headers, data=params)
    try:
        return response.json(), response.status_code
    except Exception:
        return {"error": "Antwort kein JSON", "content": response.text}, response.status_code

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json or {}
    symbol = data.get("symbol", "").upper()
    side = data.get("side", "").upper()
    quantity = data.get("quantity")
    api_key = data.get("BINGX_API_KEY")
    secret_key = data.get("BINGX_SECRET_KEY")

    if not all([symbol, side, quantity, api_key, secret_key]):
        return jsonify({"error": "Fehlende Parameter"}), 400

    result, status_code = place_market_order(symbol, side, quantity, api_key, secret_key)
    return jsonify({
        "symbol": symbol,
        "side": side,
        "quantity": quantity,
        "order_response": result,
        "status_code": status_code
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

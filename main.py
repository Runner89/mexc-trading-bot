from flask import Flask, request, jsonify
import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode

app = Flask(__name__)

BASE_URL = "https://open-api.bingx.com"
API_PATH = "/openApi/swap/v2/trade/order"

def generate_signature(params: dict, secret: str) -> str:
    """
    Erzeugt eine HMAC SHA256 Signatur für BingX.
    """
    query_string = urlencode(sorted(params.items()))
    signature = hmac.new(secret.encode(), query_string.encode(), hashlib.sha256).hexdigest()
    return signature

def place_futures_market_order(symbol, side, quantity, api_key, secret_key, source_key=None):
    """
    Sendet eine MARKET BUY oder SELL Order an BingX Swap (USDT-M) Futures.
    """
    url = BASE_URL + API_PATH
    timestamp = int(time.time() * 1000)

    params = {
        "symbol": symbol,       # z. B. "BTCUSDT"
        "side": side,           # "BUY" oder "SELL"
        "type": "MARKET",       # Order-Typ
        "quantity": quantity,   # Menge des Basiswerts
        "timestamp": timestamp
    }

    # Signatur erzeugen
    signature = generate_signature(params, secret_key)
    params["signature"] = signature

    # Header vorbereiten
    headers = {
        "X-BX-APIKEY": api_key,
        "Content-Type": "application/x-www-form-urlencoded"
    }
    if source_key:
        headers["X-SOURCE-KEY"] = source_key  # Optional für Broker-Konten

    # Request senden
    response = requests.post(url, headers=headers, data=params)

    try:
        return response.json(), response.status_code
    except Exception:
        return {"error": "Antwort ist kein JSON", "content": response.text}, response.status_code

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json or {}

    # Eingabeparameter extrahieren
    symbol = data.get("symbol", "").upper()         # z. B. "BTCUSDT"
    side = data.get("side", "").upper()             # "BUY"
    quantity = data.get("quantity")                 # z. B. "0.001"
    api_key = data.get("BINGX_API_KEY")
    secret_key = data.get("BINGX_SECRET_KEY")
    source_key = data.get("SOURCE_KEY")             # optional

    # Validierung
    if not all([symbol, side, quantity, api_key, secret_key]):
        return jsonify({"error": "Fehlende Parameter"}), 400

    # Order platzieren
    order_response, status_code = place_futures_market_order(
        symbol, side, quantity, api_key, secret_key, source_key
    )

    return jsonify({
        "symbol": symbol,
        "side": side,
        "quantity": quantity,
        "order_response": order_response,
        "status_code": status_code
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

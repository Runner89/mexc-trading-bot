import os
import time
import hmac
import hashlib
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

def get_exchange_info():
    url = "https://api.mexc.com/api/v3/exchangeInfo"
    res = requests.get(url)
    return res.json()

def get_symbol_info(symbol, exchange_info):
    for s in exchange_info.get("symbols", []):
        if s["symbol"] == symbol:
            return s
    return None

def get_price(symbol):
    url = f"https://api.mexc.com/api/v3/ticker/price?symbol={symbol}"
    res = requests.get(url)
    data = res.json()
    return float(data.get("price", 0))

def get_step_size(filters, baseSizePrecision):
    # Suche nach LOT_SIZE Filter
    for f in filters:
        if f.get("filterType") == "LOT_SIZE":
            step = float(f.get("stepSize", 1))
            if step > 0:
                return step
    # Falls kein LOT_SIZE Filter, berechne step_size aus baseSizePrecision
    try:
        precision = int(baseSizePrecision)
        return 10 ** (-precision)
    except:
        return 1

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    symbol = data.get("symbol")
    usdt_amount = data.get("usdt_amount")

    if not symbol or not usdt_amount:
        return jsonify({"error": "symbol und usdt_amount müssen angegeben werden"}), 400

    # 1. Exchange Info holen
    exchange_info = get_exchange_info()
    symbol_info = get_symbol_info(symbol, exchange_info)

    if not symbol_info:
        return jsonify({"error": "Symbol nicht gefunden"}), 400

    filters = symbol_info.get("filters", [])
    baseSizePrecision = symbol_info.get("baseSizePrecision", "0")

    step_size = get_step_size(filters, baseSizePrecision)

    # 2. Preis holen
    price = get_price(symbol)
    if price == 0:
        return jsonify({"error": "Preis für Symbol nicht gefunden"}), 400

    # 3. Menge berechnen (usdt_amount / price), auf Schrittgröße abrunden
    quantity = usdt_amount / price
    # Abrunden auf Vielfaches von step_size:
    quantity = quantity - (quantity % step_size)
    quantity = round(quantity, 8)  # auf 8 Dezimalstellen runden

    if quantity <= 0:
        return jsonify({"error": "Berechnete Menge ist 0 oder negativ"}), 400

    # 4. Order absenden
    timestamp = int(time.time() * 1000)
    query = f"symbol={symbol}&side=BUY&type=MARKET&quantity={quantity}&timestamp={timestamp}"

    secret = os.environ.get("MEXC_SECRET_KEY", "")
    api_key = os.environ.get("MEXC_API_KEY", "")

    signature = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    url = f"https://api.mexc.com/api/v3/order?{query}&signature={signature}"
    headers = {"X-MEXC-APIKEY": api_key}

    try:
        response = requests.post(url, headers=headers)
        return response.json(), response.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/", methods=["GET"])
def home():
    return "✅ MEXC Python Bot läuft"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

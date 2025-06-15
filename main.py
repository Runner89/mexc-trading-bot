import os
import time
import hmac
import hashlib
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    symbol = data.get("symbol")
    action = data.get("action")  # BUY oder SELL
    usdt_amount = float(data.get("usdt_amount", 0))

    if not all([symbol, action, usdt_amount]):
        return jsonify({"error": "Symbol, Action oder USDT-Betrag fehlt"}), 400

    # 🔁 Hole aktuelle Symbolinfos von MEXC
    url_info = "https://api.mexc.com/api/v3/exchangeInfo"
    try:
        res = requests.get(url_info)
        data_api = res.json()
    except Exception as e:
        return jsonify({"error": f"Fehler beim Abrufen der ExchangeInfo: {str(e)}"}), 500

    # 🔍 Finde das Symbol in den Daten
    symbol_info = next((s for s in data_api.get("symbols", []) if s["symbol"] == symbol), None)
    if not symbol_info:
        return jsonify({"error": "Symbol nicht gefunden"}), 400

    # 🔍 Versuche LOT_SIZE zu finden
    filters = symbol_info.get("filters", [])
    step_size = None

    for f in filters:
        if f.get("filterType") == "LOT_SIZE":
            step_size = float(f["stepSize"])
            break

    # 🔁 Fallback: falls kein Filter vorhanden → nimm baseSizePrecision
    if not step_size:
        try:
            precision = symbol_info.get("baseSizePrecision", "0.000001")
            step_size = float(precision)
        except Exception:
            return jsonify({"error": "LOT_SIZE Filter nicht gefunden und baseSizePrecision fehlt", "filters": filters}), 400

    # 🔢 Preis abrufen
    try:
        ticker = requests.get(f"https://api.mexc.com/api/v3/ticker/price?symbol={symbol}").json()
        price = float(ticker["price"])
    except Exception as e:
        return jsonify({"error": f"Fehler beim Abrufen des Preises: {str(e)}"}), 500

    # 🔄 Berechne Menge (quantity)
    quantity = usdt_amount / price
    quantity = round(quantity - (quantity % step_size), 8)

    # ✅ Trade vorbereiten
    timestamp = int(time.time() * 1000)
    query = f"symbol={symbol}&side={action}&type=MARKET&quantity={quantity}&timestamp={timestamp}"
    secret = os.environ.get("MEXC_SECRET_KEY", "")
    api_key = os.environ.get("MEXC_API_KEY", "")
    signature = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    url_order = f"https://api.mexc.com/api/v3/order?{query}&signature={signature}"
    headers = {"X-MEXC-APIKEY": api_key}

    try:
        response = requests.post(url_order, headers=headers)
        return response.text, response.status_code
    except Exception as e:
        return jsonify({"error": f"Fehler beim Senden der Order: {str(e)}"}), 500

@app.route("/", methods=["GET"])
def home():
    return "✅ MEXC Python Bot läuft (mit baseSizePrecision-Fallback)"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

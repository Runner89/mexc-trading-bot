import os
from flask import Flask, request
import time
import hmac
import hashlib
import requests
import math

app = Flask(__name__)

def get_step_size(symbol):
    url = "https://api.mexc.com/api/v3/exchangeInfo"
    try:
        res = requests.get(url)
        data = res.json()
        for s in data.get("symbols", []):
            if s["symbol"] == symbol:
                for f in s.get("filters", []):
                    if f.get("filterType") == "LOT_SIZE":
                        return float(f.get("stepSize", 1))
        return None
    except Exception as e:
        print("Fehler beim Abrufen der Step Size:", e)
        return None

def floor_quantity(qty, step):
    if step == 0:
        return qty
    precision = int(round(-math.log10(step), 0))
    return math.floor(qty / step) * step

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    symbol = data.get("symbol")
    action = data.get("action")  # z.B. BUY oder SELL
    usdt_amount = data.get("usdt_amount")

    if not all([symbol, action, usdt_amount]):
        return "Fehlende Daten: symbol, action oder usdt_amount", 400

    # Step Size abrufen
    step_size = get_step_size(symbol)
    if step_size is None:
        return "Step size für Symbol nicht gefunden", 400

    # Preis vom Symbol abrufen (notwendig für Menge)
    # Für einfache Umsetzung holen wir den aktuellen Preis per API:
    try:
        price_url = f"https://api.mexc.com/api/v3/ticker/price?symbol={symbol}"
        price_res = requests.get(price_url)
        price_data = price_res.json()
        price = float(price_data.get("price", 0))
        if price <= 0:
            return "Ungültiger Preis vom Symbol", 400
    except Exception as e:
        return f"Fehler beim Abrufen des Preises: {e}", 500

    # Menge in Symbol-Units berechnen: usdt_amount / price
    raw_qty = usdt_amount / price

    # Menge an Step Size anpassen
    quantity = floor_quantity(raw_qty, step_size)
    if quantity <= 0:
        return "Berechnete Menge ist zu klein nach Runden", 400

    timestamp = int(time.time() * 1000)
    query = f"symbol={symbol}&side={action}&type=MARKET&quantity={quantity}&timestamp={timestamp}"
    secret = os.environ.get("MEXC_SECRET_KEY", "")
    api_key = os.environ.get("MEXC_API_KEY", "")
    signature = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    url = f"https://api.mexc.com/api/v3/order?{query}&signature={signature}"
    headers = {"X-MEXC-APIKEY": api_key}

    try:
        response = requests.post(url, headers=headers)
        return response.text, response.status_code
    except Exception as e:
        return str(e), 500

@app.route("/", methods=["GET"])
def home():
    return "✅ MEXC Python Bot läuft"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

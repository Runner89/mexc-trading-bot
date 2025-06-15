import os
from flask import Flask, request
import time, hmac, hashlib, requests
import math

app = Flask(__name__)

def get_exchange_info():
    """Hole die Handelsspezifikationen für Symbole (inkl. Step Size)."""
    url = "https://api.mexc.com/api/v3/exchangeInfo"
    try:
        r = requests.get(url)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print("Error getting exchange info:", e)
        return None

def get_symbol_info(symbol, exchange_info):
    """Finde Infos für ein Symbol."""
    for s in exchange_info.get("symbols", []):
        if s["symbol"] == symbol:
            return s
    return None

def get_current_price(symbol):
    """Hole aktuellen Preis von MEXC."""
    url = f"https://api.mexc.com/api/v3/ticker/price?symbol={symbol}"
    try:
        r = requests.get(url)
        r.raise_for_status()
        data = r.json()
        return float(data["price"])
    except Exception as e:
        print("Error getting price:", e)
        return None

def adjust_quantity(quantity, step_size):
    """Runde quantity auf das Vielfache von step_size ab."""
    precision = int(round(-math.log10(step_size)))
    adjusted_qty = math.floor(quantity / step_size) * step_size
    return f"{adjusted_qty:.{precision}f}"

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    symbol = data.get("symbol")
    action = data.get("action")  # z.B. "BUY" oder "SELL"
    quantity = data.get("quantity")
    usdt_amount = data.get("usdt_amount")

    if not symbol or not action or (not quantity and not usdt_amount):
        return "Missing data: symbol, action and quantity or usdt_amount required", 400

    exchange_info = get_exchange_info()
    if not exchange_info:
        return "Error fetching exchange info", 500

    symbol_info = get_symbol_info(symbol, exchange_info)
    if not symbol_info:
        return f"Symbol {symbol} not found", 400

    # Finde stepSize in den Filters
    step_size = None
    for f in symbol_info["filters"]:
        if f["filterType"] == "LOT_SIZE":
            step_size = float(f["stepSize"])
            break

    if not step_size:
        return "Step size not found for symbol", 500

    if usdt_amount:
        price = get_current_price(symbol)
        if not price:
            return "Could not get current price", 500
        qty_float = float(usdt_amount) / price
        quantity = adjust_quantity(qty_float, step_size)
    else:
        quantity = adjust_quantity(float(quantity), step_size)

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

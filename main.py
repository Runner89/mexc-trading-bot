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

def get_step_size_and_precision(filters, baseSizePrecision):
    """
    Liefert tuple (step_size, precision).
    - step_size aus LOT_SIZE Filter oder aus baseSizePrecision.
    - precision = Anzahl Dezimalstellen, passend zur step_size.
    """
    step_size = None
    for f in filters:
        if f.get("filterType") == "LOT_SIZE":
            step_size = float(f.get("stepSize", 1))
            break
    if step_size is None or step_size == 0:
        # fallback auf baseSizePrecision
        try:
            precision = int(baseSizePrecision)
            step_size = 10 ** (-precision)
        except:
            step_size = 1
            precision = 0
    else:
        # precision ermitteln, z.B. step_size=0.001 -> precision=3
        precision = max(-int(round(math.log10(step_size))), 0)
    return step_size, precision

def get_account_balance(asset):
    secret = os.environ.get("MEXC_SECRET_KEY", "")
    api_key = os.environ.get("MEXC_API_KEY", "")
    timestamp = int(time.time() * 1000)
    params = {
        "timestamp": timestamp
    }
    query_string = "&".join([f"{k}={v}" for k, v in sorted(params.items())])
    signature = hmac.new(secret.encode(), query_string.encode(), hashlib.sha256).hexdigest()
    url = f"https://api.mexc.com/api/v3/account?{query_string}&signature={signature}"
    headers = {"X-MEXC-APIKEY": api_key}
    resp = requests.get(url, headers=headers)
    data = resp.json()
    if "balances" in data:
        for b in data["balances"]:
            if b["asset"] == asset:
                return float(b["free"])
    return 0

import math

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    symbol = data.get("symbol")
    side = data.get("side", "BUY").upper()
    usdt_amount = data.get("usdt_amount")
    quantity = data.get("quantity")

    if not symbol:
        return jsonify({"error": "symbol muss angegeben werden"}), 400

    if side not in ["BUY", "SELL"]:
        return jsonify({"error": "side muss BUY oder SELL sein"}), 400

    exchange_info = get_exchange_info()
    symbol_info = get_symbol_info(symbol, exchange_info)

    if not symbol_info:
        return jsonify({"error": "Symbol nicht gefunden"}), 400

    filters = symbol_info.get("filters", [])
    baseSizePrecision = symbol_info.get("baseSizePrecision", "0")

    step_size, precision = get_step_size_and_precision(filters, baseSizePrecision)

    # Menge ermitteln:
    if side == "SELL":
        if quantity is None:
            # Ganze Position verkaufen
            asset = symbol.replace("USDT", "")
            balance = get_account_balance(asset)
            if balance <= 0:
                return jsonify({"error": f"Keine {asset}-Position zum Verkaufen gefunden"}), 400
            quantity = balance
        else:
            quantity = float(quantity)
            if quantity <= 0:
                return jsonify({"error": "quantity muss größer als 0 sein"}), 400

    if side == "BUY":
        if usdt_amount is None:
            return jsonify({"error": "usdt_amount muss beim Kauf angegeben werden"}), 400
        price = get_price(symbol)
        if price == 0:
            return jsonify({"error": "Preis für Symbol nicht gefunden"}), 400
        quantity = usdt_amount / price

    # Auf Schrittgröße abrunden
    quantity = math.floor(quantity / step_size) * step_size

    # Auf korrekte Dezimalstellen runden
    quantity = round(quantity, precision)

    if quantity <= 0:
        return jsonify({"error": "Berechnete Menge ist 0 oder negativ"}), 400

    timestamp = int(time.time() * 1000)
    query = f"symbol={symbol}&side={side}&type=MARKET&quantity={quantity}&timestamp={timestamp}"

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

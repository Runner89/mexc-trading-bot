import os
import time
import hmac
import hashlib
import requests
from flask import Flask, request, jsonify
import datetime

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

def format_transact_time(timestamp_ms):
    dt = datetime.datetime.fromtimestamp(timestamp_ms / 1000)
    return dt.strftime('%Y-%m-%d %H:%M:%S')

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    symbol = data.get("symbol")
    usdt_amount = data.get("usdt_amount")
    side = data.get("side", "BUY").upper()

    if not symbol or (side == "BUY" and not usdt_amount):
        return jsonify({"error": "symbol und usdt_amount (bei BUY) müssen angegeben werden"}), 400

    # Exchange Info holen
    exchange_info = get_exchange_info()
    symbol_info = get_symbol_info(symbol, exchange_info)

    if not symbol_info:
        return jsonify({"error": "Symbol nicht gefunden"}), 400

    filters = symbol_info.get("filters", [])
    baseSizePrecision = symbol_info.get("baseSizePrecision", "0")

    step_size = get_step_size(filters, baseSizePrecision)

    api_key = os.environ.get("MEXC_API_KEY", "")
    secret = os.environ.get("MEXC_SECRET_KEY", "")

    timestamp = int(time.time() * 1000)

    headers = {"X-MEXC-APIKEY": api_key}

    if side == "BUY":
        price = get_price(symbol)
        if price == 0:
            return jsonify({"error": "Preis für Symbol nicht gefunden"}), 400
        quantity = usdt_amount / price
        quantity = quantity - (quantity % step_size)
        quantity = round(quantity, 8)
        if quantity <= 0:
            return jsonify({"error": "Berechnete Menge ist 0 oder negativ"}), 400
        query = f"symbol={symbol}&side=BUY&type=MARKET&quantity={quantity}&timestamp={timestamp}"
    elif side == "SELL":
        # Komplett verkaufen: Menge aus Kontostand holen
        # Konto-Info holen
        params_account = {"timestamp": timestamp}
        params_account["signature"] = hmac.new(secret.encode(), "&".join(f"{k}={v}" for k,v in sorted(params_account.items())).encode(), hashlib.sha256).hexdigest()
        headers_account = {"X-MEXC-APIKEY": api_key}
        resp_account = requests.get(f"https://api.mexc.com/api/v3/account", params=params_account, headers=headers_account)
        account_info = resp_account.json()
        if "balances" not in account_info:
            return jsonify({"error": "Konto-Info konnte nicht abgerufen werden", "details": account_info}), 500
        base_asset = symbol[:-4] if symbol.endswith("USDT") else symbol[:-3]  # Basis-Asset extrahieren, z.B. DONKEY aus DONKEYUSDT
        free_amount = 0
        for asset in account_info["balances"]:
            if asset["asset"] == base_asset:
                free_amount = float(asset["free"])
                break
        if free_amount <= 0:
            return jsonify({"error": f"Keine {base_asset} Menge zum Verkaufen gefunden"}), 400
        quantity = free_amount - (free_amount % step_size)
        quantity = round(quantity, 8)
        if quantity <= 0:
            return jsonify({"error": "Berechnete Menge ist 0 oder negativ"}), 400
        query = f"symbol={symbol}&side=SELL&type=MARKET&quantity={quantity}&timestamp={timestamp}"
    else:
        return jsonify({"error": "Nur side BUY oder SELL unterstützt"}), 400

    signature = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    url = f"https://api.mexc.com/api/v3/order?{query}&signature={signature}"

    start_time = time.time()  # Startzeit messen

    try:
        response = requests.post(url, headers=headers)
        end_time = time.time()  # Endzeit messen
        response_time = round((end_time - start_time) * 1000, 2)  # Zeit in Millisekunden

        result = response.json()
        if "transactTime" in result:
            result["transactTimeReadable"] = format_transact_time(result["transactTime"])
        
        # Füge die Zeitdauer der Antwort hinzu
        result["responseTime"] = f"{response_time} ms"

        return jsonify(result), response.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/", methods=["GET"])
def home():
    return "✅ MEXC Python Bot läuft"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

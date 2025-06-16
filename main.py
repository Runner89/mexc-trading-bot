import os
import time
import hmac
import hashlib
import requests
from flask import Flask, request, jsonify
from datetime import datetime
from zoneinfo import ZoneInfo  # Python 3.9+

app = Flask(__name__)

FIREBASE_URL = "https://test-ecb1c-default-rtdb.europe-west1.firebasedatabase.app"

# --- Firebase Funktionen ---

def firebase_loesche_kaufpreise(asset):
    url = f"{FIREBASE_URL}/kaufpreise/{asset}.json"
    response = requests.delete(url)
    print(f"Kaufpreise gelöscht für {asset}: {response.status_code}")

def firebase_speichere_kaufpreis(asset, price):
    url = f"{FIREBASE_URL}/kaufpreise/{asset}.json"
    data = {"price": price}
    response = requests.post(url, json=data)
    print(f"Kaufpreis gespeichert für {asset}: {price}")

def get_balance(asset):
    timestamp = int(time.time() * 1000)
    params = f"timestamp={timestamp}"
    secret = os.environ.get("MEXC_SECRET_KEY", "")
    signature = hmac.new(secret.encode(), params.encode(), hashlib.sha256).hexdigest()
    url = f"https://api.mexc.com/api/v3/account?{params}&signature={signature}"
    headers = {"X-MEXC-APIKEY": os.environ.get("MEXC_API_KEY", "")}
    res = requests.get(url, headers=headers)
    data = res.json()

    for item in data.get("balances", []):
        if item["asset"] == asset:
            return float(item.get("free", 0))
    return 0

def has_open_position(symbol):
    # Prüfen, ob symbol im Format "DONKEY/USDT" vorliegt
    if "/" in symbol:
        base_asset = symbol.split("/")[0]
    else:
        base_asset = symbol.replace("USDT", "")
    balance = get_balance(base_asset)
    return balance > 0, base_asset, balance

def get_exchange_info():
    url = "https://api.mexc.com/api/v3/exchangeInfo"
    res = requests.get(url)
    return res.json()

def get_symbol_info(symbol, exchange_info):
    for s in exchange_info.get("symbols", []):
        if s["symbol"] == symbol.replace("/", ""):
            return s
    return None

def get_price(symbol):
    url = f"https://api.mexc.com/api/v3/ticker/price?symbol={symbol.replace('/', '')}"
    res = requests.get(url)
    data = res.json()
    return float(data.get("price", 0))

def get_step_size(filters, baseSizePrecision):
    for f in filters:
        if f.get("filterType") == "LOT_SIZE":
            step = float(f.get("stepSize", 1))
            if step > 0:
                return step
    try:
        precision = int(baseSizePrecision)
        return 10 ** (-precision)
    except:
        return 1

def get_price_precision(filters):
    for f in filters:
        if f.get("filterType") == "PRICE_FILTER":
            tick_size = f.get("tickSize", "1")
            if '.' in tick_size:
                decimals = len(tick_size.split('.')[1].rstrip('0'))
                return decimals
    return 8

def adjust_quantity(quantity, step_size):
    precision = len(str(step_size).split('.')[-1]) if '.' in str(step_size) else 0
    adjusted_qty = quantity - (quantity % step_size)
    return round(adjusted_qty, precision)

def get_order_fills(symbol, order_id):
    timestamp = int(time.time() * 1000)
    query = f"symbol={symbol.replace('/', '')}&orderId={order_id}&timestamp={timestamp}"
    secret = os.environ.get("MEXC_SECRET_KEY", "")
    api_key = os.environ.get("MEXC_API_KEY", "")
    signature = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    url = f"https://api.mexc.com/api/v3/myTrades?{query}&signature={signature}"
    headers = {"X-MEXC-APIKEY": api_key}

    res = requests.get(url, headers=headers)
    if res.status_code == 200:
        return res.json()
    else:
        print(f"Fehler beim Abrufen der Trades: {res.text}")
        return []

def calculate_average_fill_price(fills):
    total_quantity = 0
    total_cost = 0
    for fill in fills:
        price = float(fill["price"])
        qty = float(fill["qty"])
        total_cost += price * qty
        total_quantity += qty
    if total_quantity == 0:
        return 0
    return total_cost / total_quantity

@app.route("/webhook", methods=["POST"])
def webhook():
    start_time = time.time()
    data = request.get_json()

    symbol = data.get("symbol")
    action = data.get("side", "BUY").upper()
    limit_sell_percent = data.get("limit_sell_percent", None)
    usdt_amount = data.get("usdt_amount")

    if not symbol:
        return jsonify({"error": "symbol fehlt"}), 400

    exchange_info = get_exchange_info()
    symbol_info = get_symbol_info(symbol, exchange_info)
    if not symbol_info:
        return jsonify({"error": "Symbol nicht gefunden"}), 400

    filters = symbol_info.get("filters", [])
    baseSizePrecision = symbol_info.get("baseSizePrecision", "0")
    step_size = get_step_size(filters, baseSizePrecision)

    price = get_price(symbol)
    if price == 0:
        return jsonify({"error": "Preis nicht verfügbar"}), 400

    offene_position, base_asset, balance = has_open_position(symbol)

    debug_info = {
        "base_asset": base_asset,
        "balance": balance,
        "offene_position": offene_position,
        "action": action,
        "step_size": step_size,
        "preis": price,
    }

    # Firebase nur löschen, wenn keine offene Position
    if not offene_position:
        firebase_loesche_kaufpreise(base_asset)
        debug_info["firebase_loeschen"] = True
    else:
        debug_info["firebase_loeschen"] = False

    if action == "BUY":
        if not usdt_amount:
            return jsonify({"error": "usdt_amount fehlt für BUY", **debug_info}), 400
        quantity = usdt_amount / price
    else:
        quantity = balance

    quantity = adjust_quantity(quantity, step_size)
    if quantity <= 0:
        return jsonify({"error": "Berechnete Menge ist 0 oder ungültig", **debug_info}), 400

    # Kauf-Order senden (MARKET)
    timestamp = int(time.time() * 1000)
    query = f"symbol={symbol.replace('/', '')}&side={action}&type=MARKET&quantity={quantity}&timestamp={timestamp}"
    secret = os.environ.get("MEXC_SECRET_KEY", "")
    api_key = os.environ.get("MEXC_API_KEY", "")
    signature = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    url = f"https://api.mexc.com/api/v3/order?{query}&signature={signature}"
    headers = {"X-MEXC-APIKEY": api_key}

    response = requests.post(url, headers=headers)
    response_time = (time.time() - start_time) * 1000

    if response.status_code != 200:
        return jsonify({"error": "Kauf fehlgeschlagen", "details": response.json(), **debug_info}), 400

    order_data = response.json()
    order_id = order_data.get("orderId")

    time.sleep(1)

    fills = get_order_fills(symbol, order_id)

    if fills:
        executed_price_float = calculate_average_fill_price(fills)
    else:
        print("Warnung: Keine fills für die Order gefunden, Fallback auf Orderpreis")
        executed_price = float(order_data.get("price", price))
        price_precision = get_price_precision(filters)
        executed_price_float = round(executed_price, price_precision)

    # Kaufpreis in Firebase speichern
    if action == "BUY":
        firebase_speichere_kaufpreis(base_asset, executed_price_float)

    timestamp_berlin = datetime.now(ZoneInfo("Europe/Berlin")).strftime("%Y-%m-%d %H:%M:%S")

    result = {
        "symbol": symbol,
        "side": action,
        "price": executed_price_float,
        "quantity": quantity,
        "timestamp": timestamp_berlin,
        "duration_ms": round(response_time, 2),
        **debug_info
    }

    return jsonify(result), 200

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)

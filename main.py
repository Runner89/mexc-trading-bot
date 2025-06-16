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

def firebase_get_kaufpreise(asset):
    url = f"{FIREBASE_URL}/kaufpreise/{asset}.json"
    response = requests.get(url)
    if response.status_code == 200 and response.json():
        data = response.json()
        return [float(entry["price"]) for entry in data.values() if "price" in entry]
    return []

def berechne_durchschnittspreis(preise):
    if not preise:
        return 0.0
    return sum(preise) / len(preise)

# --- MEXC API Helper ---

def get_exchange_info():
    url = "https://api.mexc.com/api/v3/exchangeInfo"
    res = requests.get(url)
    return res.json()

def get_symbol_info(symbol, exchange_info):
    for s in exchange_info.get("symbols", []):
        if s["symbol"] == symbol.replace("/", ""):  # Remove '/' falls vorhanden
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
    return 8  # Default-Fallback

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
    base_asset = get_base_asset_from_symbol(symbol)
    balance = get_balance(base_asset)
    print(f"Prüfung offene Position für {base_asset}: Balance = {balance}")
    return balance > 0

def delete_open_sell_orders(symbol):
    timestamp = int(time.time() * 1000)
    query = f"symbol={symbol.replace('/', '')}&timestamp={timestamp}"
    secret = os.environ.get("MEXC_SECRET_KEY", "")
    api_key = os.environ.get("MEXC_API_KEY", "")
    signature = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    url = f"https://api.mexc.com/api/v3/openOrders?{query}&signature={signature}"
    headers = {"X-MEXC-APIKEY": api_key}

    res = requests.get(url, headers=headers)
    if res.status_code != 200:
        print(f"Fehler beim Abrufen offener Orders: {res.text}")
        return

    orders = res.json()
    for order in orders:
        if order["side"] == "SELL" and order["type"] == "LIMIT":
            order_id = order["orderId"]
            cancel_query = f"symbol={symbol.replace('/', '')}&orderId={order_id}&timestamp={int(time.time()*1000)}"
            cancel_signature = hmac.new(secret.encode(), cancel_query.encode(), hashlib.sha256).hexdigest()
            cancel_url = f"https://api.mexc.com/api/v3/order?{cancel_query}&signature={cancel_signature}"
            cancel_res = requests.delete(cancel_url, headers=headers)
            print(f"Sell-Limit-Order {order_id} gelöscht: {cancel_res.status_code}")

def place_limit_sell_order(symbol, quantity, price):
    timestamp = int(time.time() * 1000)
    query = f"symbol={symbol.replace('/', '')}&side=SELL&type=LIMIT&quantity={quantity}&price={price}&timeInForce=GTC&timestamp={timestamp}"
    secret = os.environ.get("MEXC_SECRET_KEY", "")
    api_key = os.environ.get("MEXC_API_KEY", "")
    signature = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    url = f"https://api.mexc.com/api/v3/order?{query}&signature={signature}"
    headers = {"X-MEXC-APIKEY": api_key}

    res = requests.post(url, headers=headers)
    if res.status_code == 200:
        return res.json()
    else:
        print(f"Fehler bei Sell-Limit-Order: {res.text}")
        return None

# --- Hilfsfunktion für quantity-Rundung ---

def adjust_quantity(quantity, step_size):
    precision = len(str(step_size).split('.')[-1]) if '.' in str(step_size) else 0
    adjusted_qty = quantity - (quantity % step_size)
    return round(adjusted_qty, precision)

# --- Hilfsfunktion zur Base Asset Extraktion ---

def get_base_asset_from_symbol(symbol):
    if "/USDT" in symbol:
        return symbol.split("/USDT")[0]
    elif symbol.endswith("USDT"):
        return symbol[:-4]
    else:
        # fallback
        return symbol.replace("/", "")

# --- Neue Funktion: Trades (Fills) zu einer Order holen ---

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

# --- Webhook ---

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

    print(f"Webhook erhalten: symbol={symbol}, action={action}, usdt_amount={usdt_amount}")

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

    base_asset = get_base_asset_from_symbol(symbol)
    print(f"Base Asset ermittelt: {base_asset}")

    # Lösche Kaufpreise **vor** dem BUY, wenn keine offene Position
    if action == "BUY":
        if not has_open_position(symbol):
            print(f"Keine offene Position für {base_asset}, lösche Kaufpreise in Firebase")
            firebase_loesche_kaufpreise(base_asset)
        else:
            print(f"Offene Position für {base_asset} vorhanden - keine Löschung")

    if action == "BUY":
        if not usdt_amount:
            return jsonify({"error": "usdt_amount fehlt für BUY"}), 400
        quantity = usdt_amount / price
    else:
        quantity = get_balance(base_asset)

    quantity = adjust_quantity(quantity, step_size)
    if quantity <= 0:
        return jsonify({"error": "Berechnete Menge ist 0 oder ungültig"}), 400

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
        return jsonify({"error": "Kauf fehlgeschlagen", "details": response.json()}), 400

    order_data = response.json()
    order_id = order_data.get("orderId")
    print(f"Order erfolgreich: ID={order_id}")

    # Warte 1 Sekunde, um sicherzugehen, dass Trades registriert sind
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

    # Offene Sell-Orders löschen (optional, falls genutzt)
    delete_open_sell_orders(symbol)

    # Limit Sell Order, falls konfiguriert
    if limit_sell_percent:
        limit_sell_price = round(executed_price_float * (1 + limit_sell_percent / 100), get_price_precision(filters))
        balance = get_balance(base_asset)
        quantity_to_sell = adjust_quantity(balance, step_size)
        if quantity_to_sell > 0:
            sell_order = place_limit_sell_order(symbol, quantity_to_sell, limit_sell_price)
            if sell_order:
                print(f"Limit-Sell-Order platziert bei {limit_sell_price} für {quantity_to_sell} {base_asset}")

    timestamp_berlin = datetime.now(ZoneInfo("Europe/Berlin")).strftime("%Y-%m-%d %H:%M:%S")

    result = {
        "symbol": symbol,
        "side": action,
        "price": executed_price_float,
        "quantity": quantity,
        "timestamp": timestamp_berlin,
        "duration_ms": round(response_time, 2),
    }

    return jsonify(result), 200

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)

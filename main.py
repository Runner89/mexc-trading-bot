import os
import time
import hmac
import hashlib
import requests
from flask import Flask, request, jsonify
from datetime import datetime
from zoneinfo import ZoneInfo  # Python 3.9+

app = Flask(__name__)

FIREBASE_URL = os.environ.get("FIREBASE_URL", "")
FIREBASE_SECRET = os.environ.get("FIREBASE_SECRET", "")

# --- Firebase Funktionen ---

def firebase_loesche_kaufpreise(asset):
    url = f"{FIREBASE_URL}/kaufpreise/{asset}.json?auth={FIREBASE_SECRET}"
    response = requests.delete(url)
    print(f"Kaufpreise gelöscht für {asset}: {response.status_code}")

def firebase_speichere_kaufpreis(asset, price):
    url = f"{FIREBASE_URL}/kaufpreise/{asset}.json?auth={FIREBASE_SECRET}"
    data = {"price": price}
    response = requests.post(url, json=data)
    print(f"Kaufpreis gespeichert für {asset}: {price}")

def firebase_hole_kaufpreise(asset):
    url = f"{FIREBASE_URL}/kaufpreise/{asset}.json?auth={FIREBASE_SECRET}"
    response = requests.get(url)
    if response.status_code == 200 and response.content:
        data = response.json()
        if data:
            return [float(entry.get("price", 0)) for entry in data.values() if "price" in entry]
    return []

def berechne_durchschnitt_preis(preise):
    if not preise:
        return 0
    return sum(preise) / len(preise)

def get_exchange_info():
    url = "https://api.mexc.com/api/v3/exchangeInfo"
    return requests.get(url).json()

def get_symbol_info(symbol, exchange_info):
    for s in exchange_info.get("symbols", []):
        if s["symbol"] == symbol.replace("/", ""):
            return s
    return None

def get_price(symbol):
    url = f"https://api.mexc.com/api/v3/ticker/price?symbol={symbol.replace('/', '')}"
    data = requests.get(url).json()
    return float(data.get("price", 0))

def get_free_balance(asset):
    timestamp = int(time.time() * 1000)
    secret = os.environ.get("MEXC_SECRET_KEY", "")
    api_key = os.environ.get("MEXC_API_KEY", "")
    query = f"timestamp={timestamp}"
    signature = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    url = f"https://api.mexc.com/api/v3/account?{query}&signature={signature}"
    headers = {"X-MEXC-APIKEY": api_key}
    res = requests.get(url, headers=headers)
    if res.status_code == 200:
        balances = res.json().get("balances", [])
        for b in balances:
            if b["asset"] == asset:
                return float(b["free"])
    return None

def get_step_size(filters, baseSizePrecision):
    for f in filters:
        if f.get("filterType") == "LOT_SIZE":
            step = float(f.get("stepSize", 1))
            if step > 0:
                return step
    try:
        return 10 ** (-int(baseSizePrecision))
    except:
        return 1

def get_price_precision(filters):
    for f in filters:
        if f.get("filterType") == "PRICE_FILTER":
            tick_size = f.get("tickSize", "1")
            if '.' in tick_size:
                return len(tick_size.split('.')[1].rstrip('0'))
    return 8

def adjust_quantity(quantity, step_size):
    precision = len(str(step_size).split('.')[-1]) if '.' in str(step_size) else 0
    return round(quantity - (quantity % step_size), precision)

def get_order_fills(symbol, order_id):
    timestamp = int(time.time() * 1000)
    query = f"symbol={symbol.replace('/', '')}&orderId={order_id}&timestamp={timestamp}"
    secret = os.environ.get("MEXC_SECRET_KEY", "")
    api_key = os.environ.get("MEXC_API_KEY", "")
    signature = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    url = f"https://api.mexc.com/api/v3/myTrades?{query}&signature={signature}"
    headers = {"X-MEXC-APIKEY": api_key}
    res = requests.get(url, headers=headers)
    return res.json() if res.status_code == 200 else []

def calculate_average_fill_price(fills):
    total_quantity = total_cost = 0
    for fill in fills:
        price = float(fill["price"])
        qty = float(fill["qty"])
        total_cost += price * qty
        total_quantity += qty
    return total_cost / total_quantity if total_quantity else 0

def delete_open_limit_sell_orders(symbol):
    timestamp = int(time.time() * 1000)
    secret = os.environ.get("MEXC_SECRET_KEY", "")
    api_key = os.environ.get("MEXC_API_KEY", "")
    base_symbol = symbol.replace("/", "")
    query = f"symbol={base_symbol}&timestamp={timestamp}"
    signature = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    url = f"https://api.mexc.com/api/v3/openOrders?{query}&signature={signature}"
    headers = {"X-MEXC-APIKEY": api_key}
    res = requests.get(url, headers=headers)
    if res.status_code != 200:
        return False
    for order in res.json():
        if order["side"] == "SELL" and order["type"] == "LIMIT":
            order_id = order["orderId"]
            del_query = f"symbol={base_symbol}&orderId={order_id}&timestamp={int(time.time() * 1000)}"
            del_signature = hmac.new(secret.encode(), del_query.encode(), hashlib.sha256).hexdigest()
            del_url = f"https://api.mexc.com/api/v3/order?{del_query}&signature={del_signature}"
            requests.delete(del_url, headers=headers)
    return True

def create_limit_sell_order(symbol, quantity, price):
    timestamp = int(time.time() * 1000)
    secret = os.environ.get("MEXC_SECRET_KEY", "")
    api_key = os.environ.get("MEXC_API_KEY", "")
    base_symbol = symbol.replace("/", "")
    query = f"symbol={base_symbol}&side=SELL&type=LIMIT&timeInForce=GTC&quantity={quantity}&price={price}&timestamp={timestamp}"
    signature = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    url = f"https://api.mexc.com/api/v3/order?{query}&signature={signature}"
    headers = {"X-MEXC-APIKEY": api_key}
    return requests.post(url, headers=headers).json()

def has_open_sell_limit_order(symbol):
    timestamp = int(time.time() * 1000)
    secret = os.environ.get("MEXC_SECRET_KEY", "")
    api_key = os.environ.get("MEXC_API_KEY", "")
    base_symbol = symbol.replace("/", "")
    query = f"symbol={base_symbol}&timestamp={timestamp}"
    signature = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    url = f"https://api.mexc.com/api/v3/openOrders?{query}&signature={signature}"
    headers = {"X-MEXC-APIKEY": api_key}
    res = requests.get(url, headers=headers)
    if res.status_code != 200:
        return False
    return any(order["side"] == "SELL" and order["type"] == "LIMIT" for order in res.json())

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

    base_asset = symbol.split("/")[0] if "/" in symbol else symbol.replace("USDT", "")
    offene_position = has_open_sell_limit_order(symbol)
    usdt_balance = get_free_balance("USDT")

    debug_info = {
        "base_asset": base_asset,
        "offene_position": offene_position,
        "action": action,
        "step_size": step_size,
        "preis": price,
        "usdt_balance_free": usdt_balance
    }

    if not offene_position:
        firebase_loesche_kaufpreise(base_asset)
        debug_info["firebase_loeschen"] = True
    else:
        debug_info["firebase_loeschen"] = False

    if action == "BUY":
        if not usdt_amount:
            return jsonify({"error": "usdt_amount fehlt für BUY", **debug_info}), 400
        if usdt_balance is not None and usdt_amount > usdt_balance:
            return jsonify({"error": "Nicht genügend USDT verfügbar", **debug_info}), 400
        quantity = usdt_amount / price
    else:
        quantity = 0

    quantity = adjust_quantity(quantity, step_size)
    if quantity <= 0:
        return jsonify({"error": "Berechnete Menge ist 0 oder ungültig", **debug_info}), 400

    timestamp = int(time.time() * 1000)
    query = f"symbol={symbol.replace('/', '')}&side={action}&type=MARKET&quantity={quantity}&timestamp={timestamp}"
    secret = os.environ.get("MEXC_SECRET_KEY", "")
    api_key = os.environ.get("MEXC_API_KEY", "")
    signature = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    url = f"https://api.mexc.com/api/v3/order?{query}&signature={signature}"
    headers = {"X-MEXC-APIKEY": api_key}
    response = requests.post(url, headers=headers)

    if response.status_code != 200:
        return jsonify({"error": "Kauf fehlgeschlagen", "details": response.json(), **debug_info}), 400

    order_data = response.json()
    order_id = order_data.get("orderId")
    time.sleep(1)
    fills = get_order_fills(symbol, order_id)
    executed_price_float = calculate_average_fill_price(fills) if fills else float(order_data.get("price", price))

    if action == "BUY":
        preis_override = data.get("Preis")
        preis_zum_speichern = float(preis_override) if preis_override else executed_price_float
        firebase_speichere_kaufpreis(base_asset, preis_zum_speichern)

    kaufpreise_liste = firebase_hole_kaufpreise(base_asset)
    durchschnittlicher_kaufpreis = berechne_durchschnitt_preis(kaufpreise_liste)
    timestamp_berlin = datetime.now(ZoneInfo("Europe/Berlin")).strftime("%Y-%m-%d %H:%M:%S")

    delete_open_limit_sell_orders(symbol)

    limit_sell_price = 0
    price_rounded = 0
    if quantity > 0 and durchschnittlicher_kaufpreis > 0 and limit_sell_percent is not None:
        limit_sell_price = durchschnittlicher_kaufpreis * (1 + limit_sell_percent / 100)
        price_rounded = round(limit_sell_price, get_price_precision(filters))
        create_limit_sell_order(symbol, quantity, price_rounded)

    return jsonify({
        "symbol": symbol,
        "action": action,
        "executed_price": executed_price_float,
        "durchschnittspreis": durchschnittlicher_kaufpreis,
        "kaufpreise_alle": kaufpreise_liste,
        "timestamp": timestamp_berlin,
        "debug": debug_info,
        "limit_sell_price": limit_sell_price,
        "price_rounded": price_rounded
    })

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)

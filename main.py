#USDT Amount wird beim Webhook angegeben, der im JSON angegebene Kaufpreis in Firebase eingetragen, daraus wird der Durchschnitt berechnet und dann die Sell-Limit-Order der ganzen Position erstellt, MEXC API + Secret Key sowie Firebase Secret Key werden mit JSON gesendet

import os
import time
import hmac
import hashlib
import requests
from flask import Flask, request, jsonify
from datetime import datetime
from zoneinfo import ZoneInfo  # Python 3.9+

app = Flask(__name__)

# Firebase URL kann in der Umgebung bleiben
FIREBASE_URL = os.environ.get("FIREBASE_URL", "")

# --- Firebase Funktionen mit Secret Auth ---

def firebase_loesche_kaufpreise(asset, firebase_secret):
    url = f"{FIREBASE_URL}/kaufpreise/{asset}.json?auth={firebase_secret}"
    response = requests.delete(url)
    print(f"Kaufpreise gelöscht für {asset}: {response.status_code}")

def firebase_speichere_kaufpreis(asset, price, firebase_secret):
    url = f"{FIREBASE_URL}/kaufpreise/{asset}.json?auth={firebase_secret}"
    data = {"price": price}
    response = requests.post(url, json=data)
    print(f"Kaufpreis gespeichert für {asset}: {price}")

def firebase_hole_kaufpreise(asset, firebase_secret):
    url = f"{FIREBASE_URL}/kaufpreise/{asset}.json?auth={firebase_secret}"
    response = requests.get(url)
    if response.status_code == 200 and response.content:
        data = response.json()
        if data:
            return [float(entry.get("price", 0)) for entry in data.values() if "price" in entry]
    return []


def firebase_speichere_trade_history(trade_data, firebase_secret):
    url = f"{FIREBASE_URL}/History.json?auth={firebase_secret}"
    response = requests.post(url, json=trade_data)
    if response.status_code == 200:
        print("Trade in History gespeichert")
    else:
        print(f"Fehler beim Speichern in History: {response.text}")

def get_asset_balance(asset, api_key, secret_key):
    timestamp = int(time.time() * 1000)
    query = f"timestamp={timestamp}"
    signature = hmac.new(secret_key.encode(), query.encode(), hashlib.sha256).hexdigest()
    url = f"https://api.mexc.com/api/v3/account?{query}&signature={signature}"
    headers = {"X-MEXC-APIKEY": api_key}
    res = requests.get(url, headers=headers)

    if res.status_code == 200:
        balances = res.json().get("balances", [])
        for entry in balances:
            if entry["asset"] == asset:
                return float(entry["free"])
    else:
        print(f"Fehler beim Abrufen des Saldos: {res.text}")
    return 0.0

def berechne_durchschnitt_preis(preise):
    if not preise:
        return 0
    return sum(preise) / len(preise)

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

def get_order_fills(symbol, order_id, api_key, secret_key):
    timestamp = int(time.time() * 1000)
    query = f"symbol={symbol.replace('/', '')}&orderId={order_id}&timestamp={timestamp}"
    signature = hmac.new(secret_key.encode(), query.encode(), hashlib.sha256).hexdigest()
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

def delete_open_limit_sell_orders(symbol, api_key, secret_key):
    timestamp = int(time.time() * 1000)
    base_symbol = symbol.replace("/", "")
    query = f"symbol={base_symbol}&timestamp={timestamp}"
    signature = hmac.new(secret_key.encode(), query.encode(), hashlib.sha256).hexdigest()
    url = f"https://api.mexc.com/api/v3/openOrders?{query}&signature={signature}"
    headers = {"X-MEXC-APIKEY": api_key}

    res = requests.get(url, headers=headers)
    if res.status_code != 200:
        print(f"Fehler beim Abrufen offener Orders: {res.text}")
        return False

    orders = res.json()
    for order in orders:
        if order["side"] == "SELL" and order["type"] == "LIMIT":
            order_id = order["orderId"]
            del_query = f"symbol={base_symbol}&orderId={order_id}&timestamp={int(time.time() * 1000)}"
            del_signature = hmac.new(secret_key.encode(), del_query.encode(), hashlib.sha256).hexdigest()
            del_url = f"https://api.mexc.com/api/v3/order?{del_query}&signature={del_signature}"
            del_res = requests.delete(del_url, headers=headers)
            if del_res.status_code == 200:
                print(f"Limit Sell Order {order_id} gelöscht")
            else:
                print(f"Fehler beim Löschen der Order {order_id}: {del_res.text}")
    return True

def create_limit_sell_order(symbol, quantity, price, api_key, secret_key):
    timestamp = int(time.time() * 1000)
    base_symbol = symbol.replace("/", "")
    query = f"symbol={base_symbol}&side=SELL&type=LIMIT&timeInForce=GTC&quantity={quantity}&price={price}&timestamp={timestamp}"
    signature = hmac.new(secret_key.encode(), query.encode(), hashlib.sha256).hexdigest()
    url = f"https://api.mexc.com/api/v3/order?{query}&signature={signature}"
    headers = {"X-MEXC-APIKEY": api_key}
    res = requests.post(url, headers=headers)
    if res.status_code == 200:
        print(f"Neue Limit Sell Order erstellt zum Preis {price}")
        return res.json()
    else:
        print(f"Fehler beim Erstellen der Limit Sell Order: {res.text}")
        return None

def has_open_sell_limit_order(symbol, api_key, secret_key):
    timestamp = int(time.time() * 1000)
    base_symbol = symbol.replace("/", "")
    query = f"symbol={base_symbol}&timestamp={timestamp}"
    signature = hmac.new(secret_key.encode(), query.encode(), hashlib.sha256).hexdigest()
    url = f"https://api.mexc.com/api/v3/openOrders?{query}&signature={signature}"
    headers = {"X-MEXC-APIKEY": api_key}
    res = requests.get(url, headers=headers)
    if res.status_code != 200:
        print(f"Fehler beim Abrufen offener Orders: {res.text}")
        return False

    orders = res.json()
    for order in orders:
        if order["side"] == "SELL" and order["type"] == "LIMIT":
            return True
    return False

# ... (ALLE IMPORTS UND SETUP UNVERÄNDERT)

@app.route("/webhook", methods=["POST"])
def webhook():
    start_time = time.time()
    data = request.get_json()

    symbol = data.get("symbol")
    action = data.get("side", "BUY").upper()
    limit_sell_percent = data.get("limit_sell_percent", None)
    usdt_amount = data.get("usdt_amount")
    price_for_avg = data.get("price")  # <--- hier ist dein übergebener Preis

    # Secrets aus JSON extrahieren
    api_key = data.get("MEXC_API_KEY", "")
    secret_key = data.get("MEXC_SECRET_KEY", "")
    firebase_secret = data.get("FIREBASE_SECRET", "")

    if not symbol or not api_key or not secret_key or not firebase_secret:
        return jsonify({"error": "symbol, MEXC_API_KEY, MEXC_SECRET_KEY oder FIREBASE_SECRET fehlt"}), 400

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
    offene_position = has_open_sell_limit_order(symbol, api_key, secret_key)

    debug_info = {
        "base_asset": base_asset,
        "offene_position": offene_position,
        "action": action,
        "step_size": step_size,
        "marktpreis": price,
    }

    if not offene_position:
        firebase_loesche_kaufpreise(base_asset, firebase_secret)
        debug_info["firebase_loeschen"] = True
    else:
        debug_info["firebase_loeschen"] = False

    if action == "BUY":
        if not usdt_amount:
            return jsonify({"error": "usdt_amount fehlt für BUY", **debug_info}), 400
        quantity = usdt_amount / price
    else:
        quantity = 0

    quantity = adjust_quantity(quantity, step_size)
    if quantity <= 0:
        return jsonify({"error": "Berechnete Menge ist 0 oder ungültig", **debug_info}), 400

    # Marktorder platzieren
    timestamp = int(time.time() * 1000)
    query = f"symbol={symbol.replace('/', '')}&side={action}&type=MARKET&quantity={quantity}&timestamp={timestamp}"
    signature = hmac.new(secret_key.encode(), query.encode(), hashlib.sha256).hexdigest()
    url = f"https://api.mexc.com/api/v3/order?{query}&signature={signature}"
    headers = {"X-MEXC-APIKEY": api_key}
    response = requests.post(url, headers=headers)

    if response.status_code != 200:
        return jsonify({"error": "Kauf fehlgeschlagen", "details": response.json(), **debug_info}), 400

    order_data = response.json()
    order_id = order_data.get("orderId")

    time.sleep(1)

    fills = get_order_fills(symbol, order_id, api_key, secret_key)

    if fills:
        executed_price_float = calculate_average_fill_price(fills)
    else:
        executed_price = float(order_data.get("price", price))
        price_precision = get_price_precision(filters)
        executed_price_float = round(executed_price, price_precision)

    # Für Firebase: JSON-"price" verwenden
    if action == "BUY":
        if price_for_avg:
            try:
                price_to_store = float(price_for_avg)
                firebase_speichere_kaufpreis(base_asset, price_to_store, firebase_secret)
                debug_info["price_for_avg_used"] = price_to_store
            except ValueError:
                return jsonify({"error": "Ungültiger Preis in 'price'", **debug_info}), 400
        else:
            return jsonify({"error": "Feld 'price' fehlt für BUY", **debug_info}), 400

    # Kaufpreise laden und Durchschnitt berechnen
    kaufpreise_liste = firebase_hole_kaufpreise(base_asset, firebase_secret)
    durchschnittlicher_kaufpreis = berechne_durchschnitt_preis(kaufpreise_liste)

    if fills:
        fill_time = int(fills[0]["time"])
        timestamp_berlin = datetime.fromtimestamp(fill_time / 1000, ZoneInfo("Europe/Berlin")).strftime("%Y-%m-%d %H:%M:%S")
    else:
        timestamp_berlin = datetime.now(ZoneInfo("Europe/Berlin")).strftime("%Y-%m-%d %H:%M:%S")

    delete_open_limit_sell_orders(symbol, api_key, secret_key)

    full_quantity = get_asset_balance(base_asset, api_key, secret_key)
    full_quantity = adjust_quantity(full_quantity, step_size)

    if full_quantity > 0 and durchschnittlicher_kaufpreis > 0 and limit_sell_percent is not None:
        limit_sell_price = durchschnittlicher_kaufpreis * (1 + limit_sell_percent / 100)
        price_rounded = round(limit_sell_price, get_price_precision(filters))
        create_limit_sell_order(symbol, full_quantity, price_rounded, api_key, secret_key)
    else:
        limit_sell_price = 0
        price_rounded = 0

    usdt_invested = quantity * executed_price_float

    response_data = {
        "symbol": symbol,
        "action": action,
        "executed_price": executed_price_float,
        "usdt_invested": round(usdt_invested, 8),
        "durchschnittspreis": durchschnittlicher_kaufpreis,
        "kaufpreise_alle": kaufpreise_liste,
        "timestamp": timestamp_berlin,
        "debug": debug_info,
        "limit_sell_price": limit_sell_price,
        "price_rounded": price_rounded,
    }

    trade_entry = {
        "timestamp": timestamp_berlin,
        "symbol": symbol,
        "action": action,
        "executed_price": executed_price_float,
        "durchschnittspreis": durchschnittlicher_kaufpreis,
        "quantity": quantity,
        "usdt_invested": round(usdt_invested, 8),
        "limit_sell_percent": limit_sell_percent,
        "limit_sell_price": limit_sell_price,
    }

    firebase_speichere_trade_history(trade_entry, firebase_secret)

    return jsonify(response_data)

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)

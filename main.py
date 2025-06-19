import time
import hmac
import hashlib
import requests
from flask import Flask, request, jsonify
from datetime import datetime
from zoneinfo import ZoneInfo  # Python 3.9+

app = Flask(__name__)

FIREBASE_URL = "https://deine-firebase-url.firebaseio.com"  # Hier anpassen


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

def has_open_sell_limit_order(symbol, api_key, secret):
    timestamp = int(time.time() * 1000)
    base_symbol = symbol.replace("/", "")
    query = f"symbol={base_symbol}&timestamp={timestamp}"
    signature = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
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

def delete_open_limit_sell_orders(symbol, api_key, secret):
    timestamp = int(time.time() * 1000)
    base_symbol = symbol.replace("/", "")
    query = f"symbol={base_symbol}&timestamp={timestamp}"
    signature = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
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
            del_signature = hmac.new(secret.encode(), del_query.encode(), hashlib.sha256).hexdigest()
            del_url = f"https://api.mexc.com/api/v3/order?{del_query}&signature={del_signature}"
            del_res = requests.delete(del_url, headers=headers)
            if del_res.status_code == 200:
                print(f"Limit Sell Order {order_id} gelöscht")
            else:
                print(f"Fehler beim Löschen der Order {order_id}: {del_res.text}")
    return True

def create_limit_sell_order(symbol, quantity, price, api_key, secret):
    timestamp = int(time.time() * 1000)
    base_symbol = symbol.replace("/", "")
    query = f"symbol={base_symbol}&side=SELL&type=LIMIT&timeInForce=GTC&quantity={quantity}&price={price}&timestamp={timestamp}"
    signature = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    url = f"https://api.mexc.com/api/v3/order?{query}&signature={signature}"
    headers = {"X-MEXC-APIKEY": api_key}

    res = requests.post(url, headers=headers)
    if res.status_code == 200:
        print(f"Neue Limit Sell Order erstellt zum Preis {price}")
        return res.json()
    else:
        print(f"Fehler beim Erstellen der Limit Sell Order: {res.text}")
        return None


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()

    mexc_api_key = data.get("mexc_api_key")
    mexc_secret = data.get("mexc_secret")
    firebase_secret = data.get("firebase_secret")

    if not mexc_api_key or not mexc_secret or not firebase_secret:
        return jsonify({"error": "API Keys fehlen (mexc_api_key, mexc_secret, firebase_secret)"}), 400

    symbol = data.get("symbol")
    action = data.get("side", "BUY").upper()
    limit_sell_percent = data.get("limit_sell_percent")
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
    price_precision = get_price_precision(filters)

    aktueller_preis = get_price(symbol)
    if aktueller_preis == 0:
        return jsonify({"error": "Preis nicht verfügbar"}), 400

    if "/" in symbol:
        base_asset = symbol.split("/")[0]
    else:
        base_asset = symbol.replace("USDT", "")

    offene_position = has_open_sell_limit_order(symbol, mexc_api_key, mexc_secret)

    # Lösche Kaufpreise nur, wenn keine offene Limit Sell Order
    if not offene_position:
        firebase_loesche_kaufpreise(base_asset, firebase_secret)

    if action == "BUY":
        if not usdt_amount:
            return jsonify({"error": "usdt_amount fehlt für BUY Aktion"}), 400

        menge = round(float(usdt_amount) / aktueller_preis, 8)  # Menge berechnen
        menge = adjust_quantity(menge, step_size)
        if menge <= 0:
            return jsonify({"error": "Berechnete Menge <= 0"}), 400

        # Kauflogik hier:
        firebase_speichere_kaufpreis(base_asset, aktueller_preis, firebase_secret)

        return jsonify({
            "message": f"BUY ausgeführt für {symbol} mit Menge {menge} zum Preis {aktueller_preis}",
            "offene_position": offene_position,
            "kaufpreis": aktueller_preis,
        })

    elif action == "SELL_LIMIT":
        if not limit_sell_percent:
            return jsonify({"error": "limit_sell_percent fehlt für SELL_LIMIT Aktion"}), 400

        kaufpreise = firebase_hole_kaufpreise(base_asset, firebase_secret)
        if not kaufpreise:
            return jsonify({"error": "Keine Kaufpreise in Firebase gespeichert"}), 400

        avg_kaufpreis = berechne_durchschnitt_preis(kaufpreise)
        zielpreis = avg_kaufpreis * (1 + float(limit_sell_percent) / 100)
        zielpreis = round(zielpreis, price_precision)

        if offene_position:
            delete_open_limit_sell_orders(symbol, mexc_api_key, mexc_secret)

        menge = sum(kaufpreise) / avg_kaufpreis  # Vereinfachung: Menge = Anzahl Kaufpreise
        menge = adjust_quantity(menge, step_size)
        if menge <= 0:
            return jsonify({"error": "Berechnete Menge <= 0 für Verkauf"}), 400

        order = create_limit_sell_order(symbol, menge, zielpreis, mexc_api_key, mexc_secret)

        return jsonify({
            "message": f"SELL_LIMIT Order erstellt für {symbol} mit Menge {menge} zum Zielpreis {zielpreis}",
            "order_response": order,
            "offene_position": offene_position,
        })

    else:
        return jsonify({"error": "Unbekannte Aktion"}), 400


if __name__ == "__main__":
    app.run(debug=True, port=5000)

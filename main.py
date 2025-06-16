import os
import time
import hmac
import hashlib
import requests
from flask import Flask, request, jsonify
from datetime import datetime
from zoneinfo import ZoneInfo

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

# --- MEXC API Hilfsfunktionen ---
def get_headers():
    return {"X-MEXC-APIKEY": os.environ.get("MEXC_API_KEY", "")}

def sign_request(query_string):
    secret = os.environ.get("MEXC_SECRET_KEY", "")
    return hmac.new(secret.encode(), query_string.encode(), hashlib.sha256).hexdigest()

def has_open_position(symbol):
    timestamp = int(time.time() * 1000)
    query = f"symbol={symbol}&timestamp={timestamp}"
    signature = hmac.new(
        os.environ.get("MEXC_SECRET_KEY", "").encode(),
        query.encode(),
        hashlib.sha256
    ).hexdigest()
    url = f"https://api.mexc.com/api/v3/openOrders?{query}&signature={signature}"
    headers = {"X-MEXC-APIKEY": os.environ.get("MEXC_API_KEY", "")}
    response = requests.get(url, headers=headers)
    print("Status:", response.status_code)
    print("Antwort:", response.text)
    if response.status_code != 200:
        return False
    try:
        data = response.json()
    except Exception as e:
        print("JSON Fehler:", e)
        return False

    # Offene Orders für das Symbol vorhanden?
    for order in data:
        if order.get("symbol") == symbol:
            return True
    return False


def berechne_durchschnittspreis(preise):
    if not preise:
        return 0.0
    return sum(preise) / len(preise)

def place_market_order(symbol, side, quantity):
    timestamp = int(time.time() * 1000)
    query = f"symbol={symbol}&side={side}&type=MARKET&quantity={quantity}&timestamp={timestamp}"
    signature = sign_request(query)
    url = f"https://api.mexc.com/api/v3/order?{query}&signature={signature}"
    headers = get_headers()
    response = requests.post(url, headers=headers)
    return response

def delete_existing_sell_limit_orders(symbol):
    timestamp = int(time.time() * 1000)
    query = f"symbol={symbol}&timestamp={timestamp}"
    signature = sign_request(query)
    url = f"https://api.mexc.com/api/v3/openOrders?{query}&signature={signature}"
    headers = get_headers()
    resp = requests.get(url, headers=headers)
    if resp.status_code != 200:
        print("Fehler beim Abfragen offener Orders:", resp.text)
        return
    orders = resp.json()
    for order in orders:
        if order.get("side") == "SELL" and order.get("type") == "LIMIT":
            order_id = order.get("orderId")
            cancel_query = f"symbol={symbol}&orderId={order_id}&timestamp={int(time.time()*1000)}"
            cancel_signature = sign_request(cancel_query)
            cancel_url = f"https://api.mexc.com/api/v3/order?{cancel_query}&signature={cancel_signature}"
            cancel_resp = requests.delete(cancel_url, headers=headers)
            print(f"Limit Sell Order gelöscht: {order_id}, Status: {cancel_resp.status_code}")

def place_sell_limit_order(symbol, quantity, price):
    timestamp = int(time.time() * 1000)
    query = (f"symbol={symbol}&side=SELL&type=LIMIT&quantity={quantity}&price={price}"
             f"&timeInForce=GTC&timestamp={timestamp}")
    signature = sign_request(query)
    url = f"https://api.mexc.com/api/v3/order?{query}&signature={signature}"
    headers = get_headers()
    response = requests.post(url, headers=headers)
    return response

def get_price(symbol):
    url = f"https://api.mexc.com/api/v3/ticker/price?symbol={symbol}"
    res = requests.get(url)
    data = res.json()
    return float(data.get("price", 0))

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    symbol = data.get("symbol")
    action = data.get("side", "BUY").upper()
    limit_sell_percent = data.get("limit_sell_percent", None)
    usdt_amount = data.get("usdt_amount", None)

    if not symbol:
        return jsonify({"error": "symbol fehlt"}), 400

    base_asset = symbol.replace("USDT", "")

    if action == "BUY":

        # Prüfe offene Position; falls keine, lösche Kaufpreise
        if not has_open_position(symbol):
            firebase_loesche_kaufpreise(base_asset)

        price = get_price(symbol)
        if not price:
            return jsonify({"error": "Preis nicht verfügbar"}), 400

        if usdt_amount is None:
            return jsonify({"error": "usdt_amount fehlt für BUY"}), 400

        quantity = round(usdt_amount / price, 8)
        if quantity <= 0:
            return jsonify({"error": "Berechnete Menge <= 0"}), 400

        # Kauforder ausführen
        response = place_market_order(symbol, "BUY", quantity)
        if response.status_code != 200:
            return jsonify({"error": "Kauf fehlgeschlagen", "details": response.json()}), 400
        order_data = response.json()

        executed_price = None
        if "avgPrice" in order_data:
            executed_price = float(order_data["avgPrice"])
        elif "price" in order_data:
            executed_price = float(order_data["price"])
        else:
            executed_price = price  # fallback

        firebase_speichere_kaufpreis(base_asset, executed_price)
        alle_preise = firebase_get_kaufpreise(base_asset)
        durchschnittspreis = berechne_durchschnittspreis(alle_preise)

        # Vorherige Sell-Limit Orders löschen
        delete_existing_sell_limit_orders(symbol)

        limit_sell_price = None
        if limit_sell_percent is not None:
            try:
                limit_sell_percent = float(limit_sell_percent)
                limit_sell_price = durchschnittspreis * (1 + limit_sell_percent / 100)
                place_sell_limit_order(symbol, quantity, round(limit_sell_price, 8))
            except Exception as e:
                print("Fehler bei Limit Sell Order:", e)

        response_json = {
            "message": "Kauf ausgeführt und Daten gespeichert",
            "symbol": symbol,
            "executedPrice": executed_price,
            "averagePrice": round(durchschnittspreis, 10),
            "quantity": quantity,
            "limitSellPrice": round(limit_sell_price, 8) if limit_sell_price else None,
            "transactTime": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        }

        return jsonify(response_json), 200

    else:
        return jsonify({"error": "Nur BUY wird unterstützt"}), 400

@app.route("/", methods=["GET"])
def home():
    return "✅ MEXC Webhook läuft!"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

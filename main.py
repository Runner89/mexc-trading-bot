import os
import time
import hmac
import hashlib
import requests
from flask import Flask, request, jsonify
from datetime import datetime
from zoneinfo import ZoneInfo  # Python 3.9+

app = Flask(__name__)

# ------------------ Helper Funktionen ------------------

def sign_bingx_request(query_string, secret_key):
    """Erstellt eine HMAC SHA256 Signatur für die BingX API"""
    return hmac.new(secret_key.encode(), query_string.encode(), hashlib.sha256).hexdigest()

def get_bingx_market_price(symbol, api_key, secret_key):
    """Preis vom BingX API mit Signatur abrufen"""
    symbol = symbol.upper()
    timestamp = str(int(time.time() * 1000))
    query = f"apiKey={api_key}&symbol={symbol}&timestamp={timestamp}"
    signature = sign_bingx_request(query, secret_key)

    url = f"https://api.bingx.com/api/v1/ticker/24hr?{query}&signature={signature}"
    headers = {"X-BX-APIKEY": api_key}

    response = requests.get(url, headers=headers)
    print(f"[DEBUG] GET {url}")
    print(f"[DEBUG] Status: {response.status_code}")
    print(f"[DEBUG] Response: {response.text}")

    if response.status_code == 200:
        data = response.json()
        return float(data.get("lastPrice", 0))
    else:
        return {"error": f"API error {response.status_code}", "detail": response.text}

def create_bingx_order(symbol, quantity, price, action, api_key, secret_key):
    """Limit-Order bei BingX platzieren"""
    timestamp = str(int(time.time() * 1000))
    side = 'buy' if action.upper() == 'BUY' else 'sell'
    order_type = 'LIMIT'
    query = f"symbol={symbol}&side={side}&type={order_type}&price={price}&quantity={quantity}&timestamp={timestamp}&apiKey={api_key}"
    signature = sign_bingx_request(query, secret_key)
    url = f"https://api.bingx.com/api/v1/order?{query}&signature={signature}"
    headers = {"X-BX-APIKEY": api_key}

    response = requests.post(url, headers=headers)

    print(f"[DEBUG] Order URL: {url}")
    print(f"[DEBUG] Antwort: {response.text}")

    if response.status_code == 200:
        return response.json()
    else:
        print(f"Fehler beim Erstellen der Order: {response.text}")
        return None

def get_exchange_info():
    url = "https://api.bingx.com/api/v1/exchangeInfo"
    res = requests.get(url)
    return res.json()

def adjust_quantity(quantity, step_size):
    precision = len(str(step_size).split('.')[-1]) if '.' in str(step_size) else 0
    adjusted_qty = int(quantity / step_size) * step_size
    return round(adjusted_qty, precision)

def berechne_durchschnitt_preis(kaufpreise_liste):
    if kaufpreise_liste:
        return sum(kaufpreise_liste) / len(kaufpreise_liste)
    return 0

# ------------------ Firebase Funktionen ------------------

FIREBASE_URL = os.environ.get("FIREBASE_URL", "")

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

# ------------------ Webhook Route ------------------

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()

    symbol_raw = data.get("symbol", "")
    symbol = symbol_raw.replace("/", "-").upper()
    action = data.get("side", "BUY").upper()
    limit_sell_percent = data.get("limit_sell_percent", None)
    usdt_amount = data.get("usdt_amount")
    price_for_avg = data.get("price")

    api_key = data.get("BINGX_API_KEY", "")
    secret_key = data.get("BINGX_SECRET_KEY", "")
    firebase_secret = data.get("FIREBASE_SECRET", "")

    if not all([symbol, api_key, secret_key, firebase_secret]):
        return jsonify({"error": "Fehlende Parameter (API-Key, Secret, Symbol oder Firebase)"}), 400

    # Preis abrufen
    price_result = get_bingx_market_price(symbol, api_key, secret_key)
    if isinstance(price_result, dict) and "error" in price_result:
        return jsonify(price_result), 400
    price = price_result

    if price == 0:
       return jsonify({"error": "Preis nicht verfügbar"}), 400

    base_asset = symbol.replace("-USDT", "")
    kaufpreise_liste = firebase_hole_kaufpreise(base_asset, firebase_secret)
    durchschnittlicher_kaufpreis = berechne_durchschnitt_preis(kaufpreise_liste)

    # BUY Aktion: Preis speichern
    if action == "BUY":
        if price_for_avg:
            try:
                price_to_store = float(price_for_avg)
                firebase_speichere_kaufpreis(base_asset, price_to_store, firebase_secret)
            except ValueError:
                return jsonify({"error": "Ungültiger Preis in 'price'"}), 400
        else:
            return jsonify({"error": "Feld 'price' fehlt für BUY"}), 400

    # Menge berechnen
    if action == "BUY":
        if not usdt_amount:
            return jsonify({"error": "usdt_amount fehlt für BUY"}), 400
        quantity = usdt_amount / price
    else:
        quantity = 0

    # Schrittgröße bestimmen und Menge anpassen
    exchange_info = get_exchange_info()
    step_size = 0.01  # Fallback
    for s in exchange_info.get("symbols", []):
        if s.get("symbol") == symbol:
            for f in s.get("filters", []):
                if f.get("filterType") == "LOT_SIZE":
                    step_size = float(f.get("stepSize", 0.01))
                    break

    quantity = adjust_quantity(quantity, step_size)

    if quantity <= 0:
        return jsonify({"error": "Berechnete Menge ist 0 oder ungültig"}), 400

    # Order erstellen
    response = create_bingx_order(symbol, quantity, price, action, api_key, secret_key)
    if response:
        executed_price = float(response.get("price", price))

        # Trade Historie speichern
        trade_entry = {
            "timestamp": datetime.now(ZoneInfo("Europe/Berlin")).strftime("%Y-%m-%d %H:%M:%S"),
            "symbol": symbol,
            "action": action,
            "executed_price": executed_price,
            "durchschnittspreis": durchschnittlicher_kaufpreis,
            "quantity": quantity,
            "usdt_invested": round(usdt_amount, 8) if usdt_amount else 0,
            "limit_sell_percent": limit_sell_percent,
            "limit_sell_price": None
        }
        firebase_speichere_trade_history(trade_entry, firebase_secret)

        # Optional: Limit Sell Order
        limit_sell_price = None
        if limit_sell_percent is not None and durchschnittlicher_kaufpreis > 0:
            limit_sell_price = durchschnittlicher_kaufpreis * (1 + limit_sell_percent / 100)
            price_rounded = round(limit_sell_price, 2)
            create_bingx_order(symbol, quantity, price_rounded, "SELL", api_key, secret_key)
            trade_entry["limit_sell_price"] = price_rounded

        return jsonify({
            "symbol": symbol,
            "action": action,
            "executed_price": executed_price,
            "usdt_invested": round(usdt_amount, 8) if usdt_amount else 0,
            "durchschnittspreis": durchschnittlicher_kaufpreis,
            "kaufpreise_alle": kaufpreise_liste,
            "limit_sell_price": limit_sell_price
        })
    else:
        return jsonify({"error": "Order fehlgeschlagen"}), 400

# ------------------ App Start ------------------

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)

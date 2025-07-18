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


# --- BingX API Funktionen ---

def sign_bingx_request(query_string, secret_key):
    """ BingX verwendet auch HMAC SHA256 für die Signierung der Anfragen. """
    return hmac.new(secret_key.encode(), query_string.encode(), hashlib.sha256).hexdigest()


def get_bingx_balance(api_key, secret_key):
    """ Hole den Kontostand eines Assets von BingX """
    timestamp = str(int(time.time() * 1000))
    query = f"apiKey={api_key}&timestamp={timestamp}"
    signature = sign_bingx_request(query, secret_key)
    
    url = f"https://api.bingx.com/api/v1/account/balance?{query}&signature={signature}"
    response = requests.get(url)
    
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Fehler beim Abrufen des Saldos: {response.text}")
        return None


def get_bingx_market_price(symbol):
    """ Hole den aktuellen Marktpreis für ein Handelspaar """
    url = f"https://api.bingx.com/api/v1/market/price?symbol={symbol}"
    response = requests.get(url)
    
    if response.status_code == 200:
        data = response.json()
        return data.get("price", 0)
    else:
        print(f"Fehler beim Abrufen des Markpreises: {response.text}")
        return 0


def create_bingx_order(symbol, quantity, price, action, api_key, secret_key):
    """ Order (Kauf oder Verkauf) auf BingX erstellen """
    timestamp = str(int(time.time() * 1000))
    side = 'buy' if action.upper() == 'BUY' else 'sell'
    order_type = 'LIMIT'  # Für Limit-Orders
    query = f"symbol={symbol}&side={side}&type={order_type}&price={price}&quantity={quantity}&timestamp={timestamp}&apiKey={api_key}"
    signature = sign_bingx_request(query, secret_key)
    
    url = f"https://api.bingx.com/api/v1/order?{query}&signature={signature}"
    response = requests.post(url)
    
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
    adjusted_qty = quantity - (quantity % step_size)
    return round(adjusted_qty, precision)


# --- Webhook für BingX ---

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
    api_key = data.get("BINGX_API_KEY", "")
    secret_key = data.get("BINGX_SECRET_KEY", "")
    firebase_secret = data.get("FIREBASE_SECRET", "")

    if not symbol or not api_key or not secret_key or not firebase_secret:
        return jsonify({"error": "symbol, BINGX_API_KEY, BINGX_SECRET_KEY oder FIREBASE_SECRET fehlt"}), 400

    price = get_bingx_market_price(symbol)
    if price == 0:
        return jsonify({"error": "Preis nicht verfügbar"}), 400

    base_asset = symbol.split("/")[0] if "/" in symbol else symbol.replace("USDT", "")
    kaufpreise_liste = firebase_hole_kaufpreise(base_asset, firebase_secret)
    durchschnittlicher_kaufpreis = berechne_durchschnitt_preis(kaufpreise_liste)

    # Für Firebase: JSON-"price" verwenden
    if action == "BUY":
        if price_for_avg:
            try:
                price_to_store = float(price_for_avg)
                firebase_speichere_kaufpreis(base_asset, price_to_store, firebase_secret)
            except ValueError:
                return jsonify({"error": "Ungültiger Preis in 'price'"}), 400
        else:
            return jsonify({"error": "Feld 'price' fehlt für BUY"}), 400

    # Berechne die Menge, die mit dem verfügbaren USDT-Betrag gekauft werden kann
    if action == "BUY":
        if not usdt_amount:
            return jsonify({"error": "usdt_amount fehlt für BUY"}), 400
        quantity = usdt_amount / price
    else:
        quantity = 0

    # Die Menge anpassen
    filters = get_exchange_info().get("symbols", [])
    step_size = 0.01  # Standardgröße für das Beispiel
    quantity = adjust_quantity(quantity, step_size)

    if quantity <= 0:
        return jsonify({"error": "Berechnete Menge ist 0 oder ungültig"}), 400

    # Marktorder erstellen
    response = create_bingx_order(symbol, quantity, price, action, api_key, secret_key)
    if response:
        order_data = response
        order_id = order_data.get("orderId")
        fills = response.get("fills", [])
        executed_price = float(order_data.get("price", price))

        # Wenn Fills vorhanden sind, den ausgeführten Preis berechnen
        if fills:
            executed_price = float(fills[0]["price"])

        # Für Firebase: Historie speichern
        trade_entry = {
            "timestamp": datetime.now(ZoneInfo("Europe/Berlin")).strftime("%Y-%m-%d %H:%M:%S"),
            "symbol": symbol,
            "action": action,
            "executed_price": executed_price,
            "durchschnittspreis": durchschnittlicher_kaufpreis,
            "quantity": quantity,
            "usdt_invested": round(usdt_amount, 8),
            "limit_sell_percent": limit_sell_percent,
            "limit_sell_price": limit_sell_percent,
        }
        firebase_speichere_trade_history(trade_entry, firebase_secret)

        # Wenn eine Limit Sell Order erstellt werden soll
        if limit_sell_percent is not None and durchschnittlicher_kaufpreis > 0:
            limit_sell_price = durchschnittlicher_kaufpreis * (1 + limit_sell_percent / 100)
            price_rounded = round(limit_sell_price, 2)  # Preis auf 2 Dezimalstellen runden
            create_bingx_order(symbol, quantity, price_rounded, "SELL", api_key, secret_key)
        
        response_data = {
            "symbol": symbol,
            "action": action,
            "executed_price": executed_price,
            "usdt_invested": round(usdt_amount, 8),
            "durchschnittspreis": durchschnittlicher_kaufpreis,
            "kaufpreise_alle": kaufpreise_liste,
            "limit_sell_price": limit_sell_price,
        }
        return jsonify(response_data)

    else:
        return jsonify({"error": "Order fehlgeschlagen"}), 400


def berechne_durchschnitt_preis(kaufpreise_liste):
    """ Berechnet den Durchschnittspreis aus einer Liste von Kaufpreisen. """
    if kaufpreise_liste:
        return sum(kaufpreise_liste) / len(kaufpreise_liste)
    return 0


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)

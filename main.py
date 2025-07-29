from flask import Flask, request, jsonify
import requests
import time
import hmac
import hashlib
import json

app = Flask(__name__)

# Firebase Basis-URL (ersetze durch deine eigene)
FIREBASE_URL = "https://dein-firebase-projekt.firebaseio.com"

# --- BingX API Funktionen ---

def generate_signature(secret_key, method, endpoint, timestamp, params=None):
    """Generiere Signatur für BingX API."""
    if params:
        query_string = '&'.join([f"{k}={params[k]}" for k in sorted(params)])
    else:
        query_string = ""
    payload = f"{method}\n{endpoint}\n{timestamp}\n{query_string}"
    signature = hmac.new(secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return signature

def get_futures_balance(api_key, secret_key):
    endpoint = "/api/v1/futures/asset/balance"
    url = "https://api.bingx.com" + endpoint
    timestamp = str(int(time.time() * 1000))

    headers = {
        "X-BX-APIKEY": api_key,
        "Content-Type": "application/json"
    }

    params = {
        "timestamp": timestamp
    }

    signature = generate_signature(secret_key, "GET", endpoint, timestamp, params)
    params["signature"] = signature

    response = requests.get(url, headers=headers, params=params)
    return response.json()

def place_market_order(api_key, secret_key, symbol, usdt_amount, position_side):
    endpoint = "/api/v1/futures/order"
    url = "https://api.bingx.com" + endpoint
    timestamp = str(int(time.time() * 1000))

    headers = {
        "X-BX-APIKEY": api_key,
        "Content-Type": "application/json"
    }

    data = {
        "symbol": symbol,
        "side": "BUY" if position_side.upper() == "LONG" else "SELL",
        "positionSide": position_side.upper(),
        "type": "MARKET",
        "quoteQty": usdt_amount,
        "timestamp": int(timestamp)
    }

    signature = generate_signature(secret_key, "POST", endpoint, timestamp, data)
    data["signature"] = signature

    response = requests.post(url, headers=headers, json=data)
    return response.json()

# --- Firebase Funktionen ---

def firebase_speichere_kaufpreis(asset, price, firebase_secret):
    """Speichert einen neuen Kaufpreis unter /kaufpreise/{asset}/ mit Zeitstempel."""
    url = f"{FIREBASE_URL}/kaufpreise/{asset}.json?auth={firebase_secret}"
    daten = {
        "price": price,
        "timestamp": int(time.time())
    }
    response = requests.post(url, json=daten)
    return response.ok

def firebase_hole_kaufpreise(asset, firebase_secret):
    """Lädt alle Kaufpreise eines Assets aus Firebase."""
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

# --- Flask Webhook Endpoint ---

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json

    api_key = data.get("api_key")
    secret_key = data.get("secret_key")
    symbol = data.get("symbol", "BTC-USDT")
    usdt_amount = data.get("usdt_amount")
    position_side = data.get("position_side") or data.get("positionSide") or "LONG"
    firebase_secret = data.get("FIREBASE_SECRET")
    price_from_webhook = data.get("price")  # Preis aus Webhook

    if not api_key or not secret_key or not usdt_amount:
        return jsonify({"error": True, "msg": "api_key, secret_key and usdt_amount are required"}), 400

    # 1. Balance abrufen (nur zur Info)
    balance_response = get_futures_balance(api_key, secret_key)

    # 2. Marktorder platzieren
    order_response = place_market_order(api_key, secret_key, symbol, float(usdt_amount), position_side)

    durchschnittlicher_kaufpreis = 0
    # 3. Preis in Firebase speichern und Durchschnitt berechnen
    if firebase_secret and price_from_webhook is not None:
        try:
            price_to_store = float(price_from_webhook)
            base_asset = symbol.split("-")[0]  # z.B. BTC aus BTC-USDT
            firebase_speichere_kaufpreis(base_asset, price_to_store, firebase_secret)

            kaufpreise_liste = firebase_hole_kaufpreise(base_asset, firebase_secret)
            durchschnittlicher_kaufpreis = berechne_durchschnitt_preis(kaufpreise_liste)
        except Exception as e:
            print(f"[Firebase] Fehler beim Speichern oder Berechnen: {e}")

    return jsonify({
        "error": False,
        "available_balances": balance_response.get("data", {}).get("balance", {}),
        "order_result": order_response,
        "average_price": durchschnittlicher_kaufpreis,
        "order_params": {
            "symbol": symbol,
            "usdt_amount": usdt_amount,
            "position_side": position_side,
            "price_from_webhook": price_from_webhook
        }
    })

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)

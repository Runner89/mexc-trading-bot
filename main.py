import time
import hmac
import hashlib
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

BASE_URL = "https://open-api.bingx.com"
BALANCE_ENDPOINT = "/openApi/swap/v2/user/balance"
ORDER_ENDPOINT = "/openApi/swap/v2/trade/order"
PRICE_ENDPOINT = "/openApi/swap/v2/quote/price"

FIREBASE_URL = "https://DEIN_FIREBASE_PROJEKT.firebaseio.com"  # Ersetze durch deine Firebase URL

def generate_signature(secret_key: str, params: str) -> str:
    return hmac.new(secret_key.encode('utf-8'), params.encode('utf-8'), hashlib.sha256).hexdigest()

# Firebase Funktionen
def firebase_speichere_kaufpreis(asset, price, firebase_secret):
    url = f"{FIREBASE_URL}/kaufpreise/{asset}.json?auth={firebase_secret}"
    data = {"price": price}
    response = requests.post(url, json=data)
    return response.ok

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

def get_current_price(symbol: str):
    url = f"{BASE_URL}{PRICE_ENDPOINT}?symbol={symbol}"
    response = requests.get(url)
    data = response.json()
    if data.get("code") == 0 and "data" in data and "price" in data["data"]:
        return float(data["data"]["price"])
    return None

def place_market_order(api_key: str, secret_key: str, symbol: str, usdt_amount: float, position_side: str = "LONG"):
    price = get_current_price(symbol)
    if price is None:
        return {"code": 99999, "msg": "Failed to get current price"}

    quantity = round(usdt_amount / price, 6)
    timestamp = int(time.time() * 1000)

    params_dict = {
        "symbol": symbol,
        "side": "BUY",
        "type": "MARKET",
        "quantity": quantity,
        "positionSide": position_side,
        "timestamp": timestamp
    }

    # Alphabetisch sortieren für Signatur
    query_string = "&".join(f"{k}={params_dict[k]}" for k in sorted(params_dict))
    signature = generate_signature(secret_key, query_string)
    params_dict["signature"] = signature

    url = f"{BASE_URL}{ORDER_ENDPOINT}"
    headers = {
        "X-BX-APIKEY": api_key,
        "Content-Type": "application/json"
    }

    response = requests.post(url, headers=headers, json=params_dict)
    return response.json()

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    api_key = data.get("api_key")
    secret_key = data.get("secret_key")
    firebase_secret = data.get("FIREBASE_SECRET")
    symbol = data.get("symbol", "BTC-USDT")
    usdt_amount = data.get("usdt_amount")
    position_side = data.get("position_side", "LONG")
    price_for_avg = data.get("price")

    if not (api_key and secret_key and firebase_secret and usdt_amount and price_for_avg):
        return jsonify({"error": True, "msg": "api_key, secret_key, FIREBASE_SECRET, usdt_amount und price sind erforderlich"}), 400

    # Asset aus Symbol ableiten, z.B. BTC aus BTC-USDT
    asset = symbol.split("-")[0]

    # Preis aus Webhook in Firebase speichern
    try:
        price_float = float(price_for_avg)
    except Exception as e:
        return jsonify({"error": True, "msg": "Ungültiger Preis im Webhook"}), 400

    gespeichert = firebase_speichere_kaufpreis(asset, price_float, firebase_secret)
    if not gespeichert:
        return jsonify({"error": True, "msg": "Fehler beim Speichern des Preises in Firebase"}), 500

    # Durchschnittspreis berechnen
    kaufpreise_liste = firebase_hole_kaufpreise(asset, firebase_secret)
    durchschnittspreis = berechne_durchschnitt_preis(kaufpreise_liste)

    # Marktorder öffnen
    order_result = place_market_order(api_key, secret_key, symbol, float(usdt_amount), position_side)

    return jsonify({
        "error": False,
        "message": "Long Position eröffnet",
        "order_result": order_result,
        "durchschnittspreis_firebase": durchschnittspreis,
        "preis_aus_webhook": price_float,
        "kaufpreise_alle": kaufpreise_liste
    })

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)

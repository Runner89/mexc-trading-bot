from flask import Flask, request, jsonify
import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode
import os

app = Flask(__name__)

BASE_URL = "https://open-api.bingx.com"
FIREBASE_URL = os.getenv("FIREBASE_URL")  # Firebase URL aus Environment Variable

def generate_signature(params: dict, secret: str) -> str:
    query_string = urlencode(sorted(params.items()))
    print("Query String for signature:", query_string)
    signature = hmac.new(secret.encode(), query_string.encode(), hashlib.sha256).hexdigest()
    print("Generated signature:", signature)
    return signature

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    if not data:
        return jsonify({"error": "Kein JSON erhalten"}), 400

    # Pflichtfelder ohne firebase_secret, price, limit_sell_percent optional
    required_keys = ["symbol", "side", "usdt_amount", "BINGX_API_KEY", "BINGX_SECRET_KEY"]
    missing = [k for k in required_keys if k not in data]
    if missing:
        return jsonify({"error": f"Fehlende Felder: {missing}"}), 400

    symbol = data["symbol"]
    side = data["side"].upper()
    amount = str(data["usdt_amount"])
    api_key = data["BINGX_API_KEY"]
    secret_key = data["BINGX_SECRET_KEY"]
    price = data.get("price")  # optional
    firebase_secret = data.get("firebase_secret")  # optional
    limit_sell_percent = data.get("limit_sell_percent")  # optional

    # BingX Order erstellen
    path = "/openApi/spot/v1/trade/order"
    url = BASE_URL + path
    timestamp = int(time.time() * 1000)

    params = {
        "quoteOrderQty": amount,
        "side": side,
        "symbol": symbol,
        "timestamp": timestamp,
        "type": "MARKET"
    }

    signature = generate_signature(params, secret_key)
    params["signature"] = signature

    headers = {
        "X-BX-APIKEY": api_key,
        "Content-Type": "application/x-www-form-urlencoded"
    }

    response = requests.post(url, headers=headers, data=params)

    try:
        resp_json = response.json()
    except Exception:
        resp_json = {"error": "Antwort kein JSON", "content": response.text}

    avg_price = None
    sell_limit_order = None

    # Wenn Bestellung erfolgreich, optional Firebase Update + Durchschnitt berechnen
    if response.status_code == 200:
        if firebase_secret and price is not None:
            firebase_path = f"{FIREBASE_URL}/kaufpreise/{symbol}.json?auth={firebase_secret}"
            firebase_data = {"price": price}

            # Neuen Preis in Firebase eintragen
            firebase_response = requests.post(firebase_path, json=firebase_data)
            try:
                firebase_resp_json = firebase_response.json()
            except Exception:
                firebase_resp_json = {"error": "Firebase Antwort kein JSON", "content": firebase_response.text}

            # Alle Preise abrufen zum Durchschnitt berechnen
            get_prices_path = f"{FIREBASE_URL}/kaufpreise/{symbol}.json?auth={firebase_secret}"
            get_response = requests.get(get_prices_path)
            try:
                all_prices_data = get_response.json()
            except Exception:
                all_prices_data = {}

            prices_list = []
            if isinstance(all_prices_data, dict):
                for val in all_prices_data.values():
                    if isinstance(val, dict) and "price" in val:
                        try:
                            prices_list.append(float(val["price"]))
                        except (ValueError, TypeError):
                            pass

            if prices_list:
                avg_price = sum(prices_list) / len(prices_list)

            # Sell-Limit-Order berechnen, falls limit_sell_percent vorhanden und avg_price bekannt
            if avg_price is not None and limit_sell_percent is not None:
                try:
                    percent = float(limit_sell_percent)
                    sell_limit_order = avg_price * (1 + percent / 100)
                except (ValueError, TypeError):
                    sell_limit_order = None

            return jsonify({
                "order_status_code": response.status_code,
                "order_response": resp_json,
                "firebase_status_code": firebase_response.status_code,
                "firebase_response": firebase_resp_json,
                "average_price": avg_price,
                "sell_limit_order": sell_limit_order
            })

        else:
            # Kein Firebase Update, nur Order Response
            return jsonify({
                "order_status_code": response.status_code,
                "order_response": resp_json,
                "message": "Firebase-Daten nicht vorhanden, Firebase-Update übersprungen.",
                "average_price": None,
                "sell_limit_order": None
            })

    else:
        return jsonify({
            "order_status_code": response.status_code,
            "order_response": resp_json,
            "message": "Order fehlgeschlagen, Firebase Update nicht ausgeführt.",
            "average_price": None,
            "sell_limit_order": None
        }), 400


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

import os
import time
import random
import requests
import threading
from flask import Flask, request, jsonify
from datetime import datetime

app = Flask(__name__)

BASE_URL = "https://api.mexc.com"
FIREBASE_URL = "https://test-ecb1c-default-rtdb.europe-west1.firebasedatabase.app"

# --------- Firebase-Funktionen ---------
def firebase_loesche_kaufpreise(asset):
    url = f"{FIREBASE_URL}/kaufpreise/{asset}.json"
    response = requests.delete(url)
    if response.status_code == 200:
        print(f"Firebase: Kaufpreise für {asset} gelöscht")
    else:
        print(f"Firebase: Fehler beim Löschen für {asset}: {response.text}")

def firebase_speichere_kaufpreis(asset, price):
    url = f"{FIREBASE_URL}/kaufpreise/{asset}.json"
    data = {"price": price}
    response = requests.post(url, json=data)
    if response.status_code == 200:
        print(f"Firebase: Preis gespeichert: Asset={asset}, Price={price}")
    else:
        print(f"Firebase: Fehler beim Speichern: {response.text}")

def firebase_get_kaufpreise(asset):
    url = f"{FIREBASE_URL}/kaufpreise/{asset}.json"
    response = requests.get(url)
    if response.status_code == 200 and response.json():
        data = response.json()
        kaufpreise = [float(v["price"]) for v in data.values()]
        print(f"Firebase: Kaufpreise für {asset}: {kaufpreise}")
        return kaufpreise
    else:
        print(f"Firebase: Keine Kaufpreise für {asset} gefunden oder Fehler")
        return []

def berechne_durchschnittspreis(preise):
    if not preise:
        return 0
    return sum(preise) / len(preise)

# --------- Simulierte Orderfunktion ---------
def place_order(symbol, side, order_type, quantity=None, price=None):
    fake_price = round(random.uniform(0.002, 0.007), 6)
    print(f"Order simuliert: {side} {symbol} zum Preis {fake_price}")
    fake_response = {
        "orderId": random.randint(100000, 999999),
        "symbol": symbol,
        "side": side,
        "type": order_type,
        "status": "FILLED",
        "executedPrice": fake_price,
        "transactTime": int(time.time() * 1000)
    }
    return fake_response, 200

# --------- Flask Webhook-Handler ---------
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    symbol = data.get("symbol")
    action = data.get("side", "BUY").upper()

    if not symbol:
        return jsonify({"error": "symbol fehlt"}), 400

    base_asset = symbol.replace("USDT", "")

    if action == "BUY":
        # Falls keine Position, lösche alte Preise
        vorhandene_preise = firebase_get_kaufpreise(base_asset)
        if not vorhandene_preise:
            firebase_loesche_kaufpreise(base_asset)

        # Fiktive Order
        order, status = place_order(symbol, "BUY", "MARKET")
        if status != 200:
            return jsonify({"error": "Fehler beim simulierten Kauf", "details": order}), status

        # Preis speichern
        firebase_speichere_kaufpreis(base_asset, order["executedPrice"])

        # Durchschnitt neu berechnen
        alle_preise = firebase_get_kaufpreise(base_asset)
        durchschnittspreis = berechne_durchschnittspreis(alle_preise)

        # Antwort
        response = {
            "message": "Kauf simuliert und Preis gespeichert",
            "symbol": symbol,
            "executedPrice": order["executedPrice"],
            "averagePrice": round(durchschnittspreis, 6),
            "transactTime": datetime.fromtimestamp(order["transactTime"] / 1000).strftime("%Y-%m-%d %H:%M:%S")
        }
        return jsonify(response), 200

    else:
        return jsonify({"error": "Nur BUY wird unterstützt"}), 400

# --------- App Start ---------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)

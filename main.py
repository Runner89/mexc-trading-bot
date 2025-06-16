import os
import time
import random
import requests
from flask import Flask, request, jsonify
from datetime import datetime

app = Flask(__name__)

FIREBASE_URL = "https://test-ecb1c-default-rtdb.europe-west1.firebasedatabase.app"

# ---------- Firebase ----------
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

# ---------- Hilfsfunktionen ----------
def berechne_durchschnittspreis(preise):
    if not preise:
        return 0.0
    return sum(preise) / len(preise)

def place_order(symbol, side, order_type="MARKET"):
    # Zufälliger Preis zwischen 0.002 und 0.007
    executed_price = round(random.uniform(0.002, 0.007), 6)
    return {
        "symbol": symbol,
        "side": side,
        "type": order_type,
        "executedPrice": executed_price,
        "status": "FILLED",
        "transactTime": int(time.time() * 1000)
    }, 200

# ---------- Webhook ----------
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    symbol = data.get("symbol")
    action = data.get("side", "BUY").upper()
    limit_sell_percent = data.get("limit_sell_percent", None)

    if not symbol:
        return jsonify({"error": "symbol fehlt"}), 400

    base_asset = symbol.replace("USDT", "")

    if action == "BUY":
        vorhandene_preise = firebase_get_kaufpreise(base_asset)
        if not vorhandene_preise:
            firebase_loesche_kaufpreise(base_asset)

        order, status = place_order(symbol, "BUY")
        if status != 200:
            return jsonify({"error": "Fehler beim simulierten Kauf", "details": order}), status

        # Preis speichern
        executed_price = order["executedPrice"]
        firebase_speichere_kaufpreis(base_asset, executed_price)

        # Durchschnitt berechnen
        alle_preise = firebase_get_kaufpreise(base_asset)
        durchschnittspreis = berechne_durchschnittspreis(alle_preise)

        # Formatierte Antwort
        response = {
            "message": "Kauf simuliert und Preis gespeichert",
            "symbol": symbol,
            "executedPrice": executed_price,
            "averagePrice": round(durchschnittspreis, 10),
            "transactTime": datetime.fromtimestamp(order["transactTime"] / 1000).strftime("%Y-%m-%d %H:%M:%S")
        }

        # Optional: Limit-Sell-Preis berechnen
        if limit_sell_percent is not None:
            try:
                limit_sell_percent = float(limit_sell_percent)
                limit_sell_price = durchschnittspreis * (1 + limit_sell_percent / 100)

                # Dezimalstellen von averagePrice übernehmen
                avg_str = f"{durchschnittspreis:.10f}".rstrip("0").rstrip(".")
                decimals = len(avg_str.split(".")[1]) if "." in avg_str else 0
                fmt = f"{{:.{decimals}f}}"
                response["limitSellPrice"] = float(fmt.format(limit_sell_price))
            except Exception:
                response["warn"] = "limit_sell_percent ungültig – kein LimitSellPrice berechnet"

        return jsonify(response), 200

    else:
        return jsonify({"error": "Nur BUY wird unterstützt"}), 400

# ---------- Start ----------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)

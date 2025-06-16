import os
import time
import hmac
import hashlib
import requests
import threading
from flask import Flask, request, jsonify
from datetime import datetime
import random

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
        print(f"Firebase: Fehler beim Löschen der Kaufpreise für {asset}: {response.text}")

def firebase_speichere_kaufpreis(asset, price, quantity=None):
    url = f"{FIREBASE_URL}/kaufpreise/{asset}.json"
    data = {"price": price}  # Nur der Preis wird gespeichert
    response = requests.post(url, json=data)
    if response.status_code == 200:
        print(f"Firebase: Kaufpreis gespeichert: Asset={asset}, Price={price}")
    else:
        print(f"Firebase: Fehler beim Speichern: {response.text}")

def firebase_get_kaufpreise(asset):
    url = f"{FIREBASE_URL}/kaufpreise/{asset}.json"
    response = requests.get(url)
    if response.status_code == 200 and response.json():
        data = response.json()
        kaufpreise_mengen = [(float(v["price"]), float(v["quantity"])) for v in data.values()]
        print(f"Firebase: Lade Kaufpreise für {asset}: {kaufpreise_mengen}")
        return kaufpreise_mengen
    else:
        print(f"Firebase: Keine Kaufpreise für {asset} gefunden oder Fehler")
        return []

# --------- Hilfsfunktionen ---------
def berechne_durchschnittspreis(kaufpreise_mengen):
    if not kaufpreise_mengen:
        return 0
    gesamtmenge = sum(qty for _, qty in kaufpreise_mengen)
    if gesamtmenge == 0:
        return 0
    gewichteter_preis = sum(price * qty for price, qty in kaufpreise_mengen)
    return gewichteter_preis / gesamtmenge

def get_exchange_info():
    url = f"{BASE_URL}/api/v3/exchangeInfo"
    res = requests.get(url)
    return res.json()

def get_symbol_info(symbol, exchange_info):
    for s in exchange_info.get("symbols", []):
        if s["symbol"] == symbol:
            return s
    return None

def get_price(symbol):
    url = f"{BASE_URL}/api/v3/ticker/price?symbol={symbol}"
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

def get_balance(asset):
    # Für Testzwecke hier immer 0 zurückgeben (oder beliebigen Wert)
    # Du kannst hier auch echte MEXC-API-Anbindung machen, wenn gewünscht
    print(f"Balance-Abfrage für {asset} simuliert: 1.2345")
    return 1.2345  # Simulierte Menge

# --------- Simulierte Orderfunktion (kein Echtauftrag!) ---------
def place_order(symbol, side, order_type, quantity=None, price=None):
    # Fiktiver Kaufpreis als Zufallswert zwischen 0.002 und 0.007 bei BUY
    if side == "BUY":
        price = round(random.uniform(0.002, 0.007), 6)
    print(f"Order simuliert: {side} {quantity} {symbol} @ {price if price else 'MARKET'}")
    fake_response = {
        "orderId": 123456,
        "symbol": symbol,
        "side": side,
        "type": order_type,
        "price": str(price) if price else "",
        "status": "FILLED",
        "fills": [{"price": str(price if price else 1), "qty": str(quantity)}],
        "transactTime": int(time.time() * 1000)
    }
    return fake_response, 200

def cancel_open_limit_sell(symbol):
    print(f"Simuliere Abbruch offener Limit-Sell Orders für {symbol}")
    return []

# --------- Hintergrundprozess für Firebase und Limit-Sell ---------
def hintergrund_verkauf(symbol, base_asset, limit_sell_percent, step_size):
    kaufpreise_mengen = firebase_get_kaufpreise(base_asset)
    durchschnittspreis = berechne_durchschnittspreis(kaufpreise_mengen)
    if durchschnittspreis == 0:
        print("Kein Durchschnittspreis verfügbar, Limit-Sell übersprungen")
        return

    limit_sell_price = round(durchschnittspreis * (1 + limit_sell_percent / 100), 8)

    print(f"Setze Limit-Sell-Order bei {limit_sell_price} für {symbol}")

    cancel_open_limit_sell(symbol)

    gesamtmenge = get_balance(base_asset)
    gesamtmenge = gesamtmenge - (gesamtmenge % step_size)
    gesamtmenge = round(gesamtmenge, 8)
    if gesamtmenge <= 0:
        print("Keine Menge zum Verkaufen, Limit-Sell übersprungen")
        return

    place_order(symbol, "SELL", "LIMIT", quantity=gesamtmenge, price=limit_sell_price)

@app.route("/webhook", methods=["POST"])
def webhook():
    start_time = time.time()

    data = request.get_json()
    symbol = data.get("symbol")
    action = data.get("side", "BUY").upper()
    usdt_amount = data.get("usdt_amount")
    limit_sell_percent = data.get("limit_sell_percent", 1)  # Standard 1%

    if not symbol:
        return jsonify({"error": "symbol fehlt"}), 400

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

    base_asset = symbol.replace("USDT", "")

    if action == "BUY":
        if not usdt_amount:
            return jsonify({"error": "usdt_amount fehlt für BUY"}), 400

        # Wenn keine offene Position, alte Kaufpreise löschen
        if get_balance(base_asset) == 0:
            firebase_loesche_kaufpreise(base_asset)

        quantity = usdt_amount / price
        quantity = quantity - (quantity % step_size)
        quantity = round(quantity, 8)
        if quantity <= 0:
            return jsonify({"error": "Berechnete Menge ist 0 oder ungültig"}), 400

        buy_order, status = place_order(symbol, "BUY", "MARKET", quantity=quantity)
        if status != 200:
            return jsonify({"error": "Buy-Order fehlgeschlagen", "details": buy_order}), status

        fills = buy_order.get("fills", [])
        if fills:
            avg_price = sum(float(f["price"]) * float(f["qty"]) for f in fills) / sum(float(f["qty"]) for f in fills)
            filled_qty = sum(float(f["qty"]) for f in fills)
        else:
            avg_price = price
            filled_qty = quantity

        def speicher_und_sell():
            firebase_speichere_kaufpreis(base_asset, avg_price, filled_qty)
            hintergrund_verkauf(symbol, base_asset, limit_sell_percent, step_size)

        threading.Thread(target=speicher_und_sell).start()

        # Gesamt-Durchschnitt aller Kaufpreise holen und zurückgeben
        alle_kaufpreise = firebase_get_kaufpreise(base_asset)
        durchschnittspreis_total = berechne_durchschnittspreis(alle_kaufpreise)

        response_time = (time.time() - start_time) * 1000
        buy_order["responseTime"] = f"{response_time:.2f} ms"
        buy_order["transactTimeReadable"] = datetime.fromtimestamp(buy_order.get("transactTime", 0) / 1000).strftime("%Y-%m-%d %H:%M:%S")
        buy_order["avg_price_total"] = round(durchschnittspreis_total, 8)

        return jsonify(buy_order), 200

    elif action == "SELL":
        quantity = data.get("quantity")
        if not quantity:
            return jsonify({"error": "quantity fehlt für SELL"}), 400
        quantity = float(quantity)

        sell_order, status = place_order(symbol, "SELL", "MARKET", quantity=quantity)
        if status != 200:
            return jsonify({"error": "Sell-Order fehlgeschlagen", "details": sell_order}), status

        return jsonify(sell_order), 200

    else:
        return jsonify({"error": "Unbekannte Aktion"}), 400

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))  # Port von Render wird automatisch über Umgebungsvariable gesetzt
    app.run(host="0.0.0.0", port=port, debug=True)

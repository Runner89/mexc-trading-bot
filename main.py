import os
import time
import hmac
import hashlib
import requests
from flask import Flask, request, jsonify
from datetime import datetime
from zoneinfo import ZoneInfo

app = Flask(__name__)

BASE_URL = "https://open-api.bingx.com"

def generate_signature(params: dict, secret: str) -> str:
    # URL-kodierter Query-String, sortiert nach Keys
    query_string = urlencode(sorted(params.items()))
    print("Query String for signature:", query_string)
    signature = hmac.new(secret.encode(), query_string.encode(), hashlib.sha256).hexdigest()
    print("Generated signature:", signature)
    return signature


FIREBASE_URL = os.environ.get("FIREBASE_URL", "")

# --- Firebase Funktionen ---

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

def sign_request(query_string, secret_key):
    return hmac.new(secret_key.encode(), query_string.encode(), hashlib.sha256).hexdigest()

def get_asset_balance_bingx(asset, api_key, secret_key):
    timestamp = int(time.time() * 1000)
    query = f"timestamp={timestamp}"
    signature = sign_request(query, secret_key)
    url = f"https://api.bingx.com/api/v1/account/balance?{query}&signature={signature}"
    headers = {"X-BINGX-APIKEY": api_key}
    res = requests.get(url, headers=headers)
    if res.status_code == 200:
        balances = res.json().get("data", [])
        for entry in balances:
            if entry["asset"] == asset:
                return float(entry["free"])
    else:
        print(f"Fehler beim Abrufen des Saldos: {res.text}")
    return 0.0

def delete_open_limit_sell_orders(symbol, api_key, secret_key):
    timestamp = int(time.time() * 1000)
    query = f"symbol={symbol}&timestamp={timestamp}"
    signature = sign_request(query, secret_key)
    url = f"https://api.bingx.com/api/v1/order/openOrders?{query}&signature={signature}"
    headers = {"X-BINGX-APIKEY": api_key}
    res = requests.get(url, headers=headers)
    if res.status_code != 200:
        print(f"Fehler beim Abrufen offener Orders: {res.text}")
        return False
    orders = res.json().get("data", [])
    for order in orders:
        if order["side"] == "SELL" and order["type"] == "LIMIT":
            order_id = order["orderId"]
            del_query = f"symbol={symbol}&orderId={order_id}&timestamp={int(time.time() * 1000)}"
            del_signature = sign_request(del_query, secret_key)
            del_url = f"https://api.bingx.com/api/v1/order?{del_query}&signature={del_signature}"
            del_res = requests.delete(del_url, headers=headers)
            if del_res.status_code == 200:
                print(f"Limit Sell Order {order_id} gelöscht")
            else:
                print(f"Fehler beim Löschen der Order {order_id}: {del_res.text}")
    return True

def create_market_order(symbol, quantity, api_key, secret_key):
    url = "https://open-api.bingx.com/openApi/spot/v1/trade/order"
    timestamp = str(int(time.time() * 1000))

    params = {
        "symbol": symbol,
        "side": "BUY",
        "type": "MARKET",
        "quantity": quantity,
        "timestamp": timestamp
    }

    # Signatur generieren
    signature = generate_signature(params, secret_key)
    params["signature"] = signature

    headers = {
        "X-BX-APIKEY": api_key,
        "Content-Type": "application/x-www-form-urlencoded"
    }

    try:
        response = requests.post(url, headers=headers, data=params)
        response_json = response.json()
        print("DEBUG: Marktorder API Response:", response_json)
        return response_json
    except Exception as e:
        print(f"Fehler bei create_market_order(): {e}")
        return {
            "code": -1,
            "msg": str(e)
        }


def create_limit_sell_order(symbol, quantity, price, api_key, secret_key):
    timestamp = int(time.time() * 1000)
    query = f"symbol={symbol}&side=SELL&type=LIMIT&timeInForce=GTC&quantity={quantity}&price={price}&timestamp={timestamp}"
    signature = sign_request(query, secret_key)
    url = f"https://api.bingx.com/api/v1/order?{query}&signature={signature}"
    headers = {"X-BINGX-APIKEY": api_key}
    res = requests.post(url, headers=headers)
    if res.status_code == 200:
        print(f"Limit Sell Order erstellt zum Preis {price}")
        return res.json()
    else:
        print(f"Fehler beim Erstellen der Limit Sell Order: {res.text}")
        return None

def has_open_sell_limit_order(symbol, api_key, secret_key):
    timestamp = int(time.time() * 1000)
    query = f"symbol={symbol}&timestamp={timestamp}"
    signature = sign_request(query, secret_key)
    url = f"https://api.bingx.com/api/v1/order/openOrders?{query}&signature={signature}"
    headers = {"X-BINGX-APIKEY": api_key}
    res = requests.get(url, headers=headers)
    if res.status_code != 200:
        print(f"Fehler beim Abrufen offener Orders: {res.text}")
        return False
    orders = res.json().get("data", [])
    for order in orders:
        if order["side"] == "SELL" and order["type"] == "LIMIT":
            return True
    return False

# --- Hilfsfunktionen ---

def berechne_durchschnitt_preis(preise):
    if not preise:
        return 0
    return sum(preise) / len(preise)

def adjust_quantity(quantity, step=0.000001):
    # Rundet auf den nächsten Schritt nach unten
    return float(f"{int(quantity / step) * step:.6f}")

# --- Flask Route ---

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()

    symbol = data.get("symbol")
    action = data.get("side", "BUY").upper()
    usdt_amount = data.get("usdt_amount")
    limit_sell_percent = data.get("limit_sell_percent", None)
    price_for_avg = data.get("price")

    api_key = data.get("BINGX_API_KEY", "")
    secret_key = data.get("BINGX_SECRET_KEY", "")
    firebase_secret = data.get("FIREBASE_SECRET", "")

    if not symbol or not api_key or not secret_key or not firebase_secret:
        return jsonify({"error": "symbol, BINGX_API_KEY, BINGX_SECRET_KEY oder FIREBASE_SECRET fehlt"}), 400

    if price_for_avg is None:
        return jsonify({"error": "'price' Feld wird benötigt"}), 400

    try:
        price = float(price_for_avg)
    except ValueError:
        return jsonify({"error": "Ungültiger Preis im Feld 'price'"}), 400

    base_asset = symbol.split("-")[0]

    offene_position = has_open_sell_limit_order(symbol, api_key, secret_key)

    debug_info = {
        "base_asset": base_asset,
        "offene_position": offene_position,
        "action": action,
    }

    if not offene_position:
        firebase_loesche_kaufpreise(base_asset, firebase_secret)
        debug_info["firebase_loeschen"] = True
    else:
        debug_info["firebase_loeschen"] = False

    limit_sell_price = 0
    price_rounded = 0

    if action == "BUY":
        if usdt_amount is None:
            return jsonify({"error": "usdt_amount fehlt für BUY", **debug_info}), 400
        quantity = usdt_amount / price
        quantity = adjust_quantity(quantity)
        if quantity <= 0:
            return jsonify({"error": "Berechnete Menge ist 0 oder ungültig", **debug_info}), 400
        
        order_response = create_market_order(symbol, quantity, api_key, secret_key)
        print("DEBUG: order_response =", order_response)

        if not order_response:
            return jsonify({"error": "Marktorder konnte nicht erstellt werden", **debug_info}), 500

        try:
            firebase_speichere_kaufpreis(base_asset, price, firebase_secret)
            debug_info["price_for_avg_used"] = price
        except Exception as e:
            debug_info["firebase_speicherfehler"] = str(e)

        kaufpreise_liste = firebase_hole_kaufpreise(base_asset, firebase_secret)
        durchschnittlicher_kaufpreis = berechne_durchschnitt_preis(kaufpreise_liste)

        full_quantity = get_asset_balance_bingx(base_asset, api_key, secret_key)

        delete_open_limit_sell_orders(symbol, api_key, secret_key)

        if full_quantity > 0 and durchschnittlicher_kaufspreis > 0 and limit_sell_percent is not None:
            try:
                limit_sell_price = durchschnittlicher_kaufspreis * (1 + float(limit_sell_percent) / 100)
                price_rounded = round(limit_sell_price, 2)
                create_limit_sell_order(symbol, full_quantity, price_rounded, api_key, secret_key)
            except Exception as e:
                debug_info["limit_sell_order_fehlgeschlagen"] = str(e)
        else:
            limit_sell_price = 0
            price_rounded = 0

        trade_history_data = {
            "timestamp": datetime.now(ZoneInfo("Europe/Berlin")).isoformat(),
            "symbol": symbol,
            "side": action,
            "quantity": quantity,
            "price": price,
            "status": "completed"
        }
        firebase_speichere_trade_history(trade_history_data, firebase_secret)

        response_data = {
            "symbol": symbol,
            "action": action,
            "executed_price": price,
            "usdt_invested": round(usdt_amount, 8),
            "durchschnittspreis": durchschnittlicher_kaufspreis,
            "kaufpreise_alle": kaufpreise_liste,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "debug": debug_info,
            "limit_sell_price": limit_sell_price,
            "price_rounded": price_rounded
        }
        return jsonify(response_data)

    else:
        return jsonify({"error": "Nur BUY Aktion wird aktuell unterstützt", **debug_info}), 400


if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=5000)



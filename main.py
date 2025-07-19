import os
import time
import hmac
import hashlib
import requests
import urllib.parse
from flask import Flask, request, jsonify
from datetime import datetime
from zoneinfo import ZoneInfo

app = Flask(__name__)

FIREBASE_URL = os.environ.get("FIREBASE_URL", "")  # z. B. "https://deinprojekt.firebaseio.com"

# --- HMAC Signatur-Funktion ---

def generate_signature(params, secret_key):
    query_string = urllib.parse.urlencode(params)
    return hmac.new(secret_key.encode(), query_string.encode(), hashlib.sha256).hexdigest()

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

def get_asset_balance_bingx(asset, api_key, secret_key):
    timestamp = int(time.time() * 1000)
    query = f"timestamp={timestamp}"
    signature = generate_signature({"timestamp": timestamp}, secret_key)
    url = f"https://api.bingx.com/api/v1/account/balance?timestamp={timestamp}&signature={signature}"
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
    params = {"symbol": symbol, "timestamp": timestamp}
    signature = generate_signature(params, secret_key)
    url = f"https://api.bingx.com/api/v1/order/openOrders?{urllib.parse.urlencode(params)}&signature={signature}"
    headers = {"X-BINGX-APIKEY": api_key}
    res = requests.get(url, headers=headers)
    if res.status_code != 200:
        print(f"Fehler beim Abrufen offener Orders: {res.text}")
        return False
    orders = res.json().get("data", [])
    for order in orders:
        if order["side"] == "SELL" and order["type"] == "LIMIT":
            order_id = order["orderId"]
            del_params = {
                "symbol": symbol,
                "orderId": order_id,
                "timestamp": int(time.time() * 1000)
            }
            del_signature = generate_signature(del_params, secret_key)
            del_url = f"https://api.bingx.com/api/v1/order?{urllib.parse.urlencode(del_params)}&signature={del_signature}"
            del_res = requests.delete(del_url, headers=headers)
            print(f"Order gelöscht: {del_res.status_code} {del_res.text}")
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

    signature = generate_signature(params, secret_key)
    params["signature"] = signature

    headers = {
        "X-BX-APIKEY": api_key,
        "Content-Type": "application/x-www-form-urlencoded"
    }

    try:
        response = requests.post(url, headers=headers, data=params)
        response_json = response.json()
        print("MARKET ORDER RESPONSE:", response_json)
        return response_json
    except Exception as e:
        print("Fehler bei create_market_order():", str(e))
        return None

def create_limit_sell_order(symbol, quantity, price, api_key, secret_key):
    timestamp = int(time.time() * 1000)
    params = {
        "symbol": symbol,
        "side": "SELL",
        "type": "LIMIT",
        "timeInForce": "GTC",
        "quantity": quantity,
        "price": price,
        "timestamp": timestamp
    }
    signature = generate_signature(params, secret_key)
    url = f"https://api.bingx.com/api/v1/order?{urllib.parse.urlencode(params)}&signature={signature}"
    headers = {"X-BINGX-APIKEY": api_key}
    res = requests.post(url, headers=headers)
    if res.status_code == 200:
        print(f"Limit Sell Order erstellt zu {price}")
        return res.json()
    else:
        print(f"Fehler bei Limit Sell Order: {res.text}")
        return None

def has_open_sell_limit_order(symbol, api_key, secret_key):
    timestamp = int(time.time() * 1000)
    params = {"symbol": symbol, "timestamp": timestamp}
    signature = generate_signature(params, secret_key)
    url = f"https://api.bingx.com/api/v1/order/openOrders?{urllib.parse.urlencode(params)}&signature={signature}"
    headers = {"X-BINGX-APIKEY": api_key}
    res = requests.get(url, headers=headers)
    if res.status_code != 200:
        print(f"Fehler beim Abrufen offener Orders: {res.text}")
        return False
    orders = res.json().get("data", [])
    return any(order["side"] == "SELL" and order["type"] == "LIMIT" for order in orders)

# --- Hilfsfunktionen ---

def berechne_durchschnitt_preis(preise):
    if not preise:
        return 0
    return sum(preise) / len(preise)

def adjust_quantity(quantity, step=0.000001):
    return float(f"{int(quantity / step) * step:.6f}")

# --- Flask Webhook ---

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

    if not all([symbol, api_key, secret_key, firebase_secret]):
        return jsonify({"error": "Pflichtfelder fehlen"}), 400

    try:
        price = float(price_for_avg)
    except Exception:
        return jsonify({"error": "Ungültiger Preis"}), 400

    base_asset = symbol.split("-")[0]
    offene_position = has_open_sell_limit_order(symbol, api_key, secret_key)

    debug_info = {
        "base_asset": base_asset,
        "offene_position": offene_position,
        "firebase_loeschen": False
    }

    if not offene_position:
        firebase_loesche_kaufpreise(base_asset, firebase_secret)
        debug_info["firebase_loeschen"] = True

    quantity = adjust_quantity(usdt_amount / price)

    response = create_market_order(symbol, quantity, api_key, secret_key)
    if not response or response.get("code") != 0:
        print("Fehler bei Marktorder:", response)
        return jsonify({
            "error": "Marktorder konnte nicht erstellt werden",
            "action": action,
            "base_asset": base_asset,
            **debug_info
        }), 500

    firebase_speichere_kaufpreis(base_asset, price, firebase_secret)
    kaufpreise_liste = firebase_hole_kaufpreise(base_asset, firebase_secret)
    durchschnittlicher_kaufpreis = berechne_durchschnitt_preis(kaufpreise_liste)

    full_quantity = get_asset_balance_bingx(base_asset, api_key, secret_key)

    limit_sell_price = 0
    price_rounded = 0

    if full_quantity > 0 and durchschnittlicher_kaufpreis > 0 and limit_sell_percent:
        limit_sell_price = durchschnittlicher_kaufpreis * (1 + float(limit_sell_percent) / 100)
        price_rounded = round(limit_sell_price, 2)
        create_limit_sell_order(symbol, full_quantity, price_rounded, api_key, secret_key)

    firebase_speichere_trade_history({
        "timestamp": datetime.now(ZoneInfo("Europe/Berlin")).isoformat(),
        "symbol": symbol,
        "side": action,
        "quantity": quantity,
        "price": price,
        "status": "completed"
    }, firebase_secret)

    return jsonify({
        "symbol": symbol,
        "action": action,
        "executed_price": price,
        "usdt_invested": round(usdt_amount, 8),
        "durchschnittspreis": durchschnittlicher_kaufpreis,
        "kaufpreise_alle": kaufpreise_liste,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "debug": debug_info,
        "limit_sell_price": limit_sell_price,
        "price_rounded": price_rounded
    })

# --- Server Start ---

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)

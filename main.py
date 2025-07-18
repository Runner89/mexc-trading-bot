import os
import time
import hmac
import hashlib
import requests
from flask import Flask, request, jsonify
from datetime import datetime
from zoneinfo import ZoneInfo

app = Flask(__name__)

FIREBASE_URL = os.environ.get("FIREBASE_URL", "")

# --- Firebase Funktionen mit Secret Auth ---

def firebase_loesche_kaufpreise(asset, firebase_secret):
    url = f"{FIREBASE_URL}/kaufpreise/{asset}.json?auth={firebase_secret}"
    requests.delete(url)

def firebase_speichere_kaufpreis(asset, price, firebase_secret):
    url = f"{FIREBASE_URL}/kaufpreise/{asset}.json?auth={firebase_secret}"
    data = {"price": price}
    requests.post(url, json=data)

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
    requests.post(url, json=trade_data)

# --- MEXC FUTURES Funktionen ---

def futures_sign(api_key, api_secret, params):
    t = int(time.time() * 1000)
    params['api_key'] = api_key
    params['req_time'] = t
    sorted_params = sorted(params.items())
    query = '&'.join([f"{k}={v}" for k, v in sorted_params])
    to_sign = query + f"&secret_key={api_secret}"
    sign = hashlib.md5(to_sign.encode()).hexdigest().upper()
    params['sign'] = sign
    return params

def convert_symbol_to_futures(symbol):
    return symbol.replace("/", "_")

def get_futures_price(symbol):
    url = f"https://contract.mexc.com/api/v1/contract/ticker"
    try:
        res = requests.get(url, params={"symbol": symbol}, timeout=10)
        res.raise_for_status()
        data = res.json()

        if "data" in data and data["data"] and "last_price" in data["data"]:
            return float(data["data"]["last_price"])
        else:
            print(f"[Fehler] Ungültige API-Antwort für Symbol {symbol}: {data}")
            return -1  # oder raise ValueError(...)
    except Exception as e:
        print(f"[Exception] Fehler beim Abrufen des Futures-Preises: {e}")
        return -1

def send_futures_order(symbol, quantity, side, api_key, api_secret):
    url = "https://contract.mexc.com/api/v1/private/order/submit"
    params = {
        "symbol": symbol,
        "price": 0,
        "vol": quantity,
        "side": 1 if side == "BUY" else 2,
        "type": 2,
        "open_type": 1,
        "position_id": 0,
        "leverage": 1,
        "external_oid": f"order_{int(time.time())}",
        "position_mode": 1,
        "reduce_only": False,
    }
    signed_params = futures_sign(api_key, api_secret, params)
    res = requests.post(url, data=signed_params)
    return res.json()

def create_limit_futures_sell_order(symbol, quantity, price, api_key, api_secret):
    url = "https://contract.mexc.com/api/v1/private/order/submit"
    params = {
        "symbol": symbol,
        "price": price,
        "vol": quantity,
        "side": 2,
        "type": 1,
        "open_type": 1,
        "position_id": 0,
        "leverage": 1,
        "external_oid": f"limit_{int(time.time())}",
        "position_mode": 1,
        "reduce_only": True
    }
    signed_params = futures_sign(api_key, api_secret, params)
    res = requests.post(url, data=signed_params)
    return res.json()

def get_futures_position(symbol, api_key, api_secret):
    url = "https://contract.mexc.com/api/v1/private/position/list/isolated"
    signed_params = futures_sign(api_key, api_secret, {})
    res = requests.get(url, params=signed_params)
    data = res.json()
    for pos in data.get("data", []):
        if pos["symbol"] == symbol:
            return pos
    return None

def berechne_durchschnitt_preis(preise):
    return sum(preise) / len(preise) if preise else 0

@app.route("/webhook", methods=["POST"])
def webhook():

    data = request.get_json()
    print(f"[DEBUG] Empfangene Daten: {data}")
    symbol = data.get("symbol", "").strip()
    print(f"[DEBUG] Symbol: '{symbol}'")
    
    futures_symbol = convert_symbol_to_futures(symbol)
    print(f"[DEBUG] Futures Symbol: '{futures_symbol}'")
    data = request.get_json()
    symbol = data.get("symbol")
    action = data.get("side", "BUY").upper()
    usdt_amount = data.get("usdt_amount")
    price_for_avg = data.get("price")
    limit_sell_percent = data.get("limit_sell_percent")

    api_key = data.get("MEXC_API_KEY")
    secret_key = data.get("MEXC_SECRET_KEY")
    firebase_secret = data.get("FIREBASE_SECRET")

    if not all([symbol, api_key, secret_key, firebase_secret]):
        return jsonify({"error": "Pflichtfelder fehlen"}), 400

    futures_symbol = convert_symbol_to_futures(symbol)
    market_price = get_futures_price(futures_symbol)

    if market_price <= 0:
       return jsonify({"error": "Ungültiger oder nicht abrufbarer Marktpreis"}), 400

    base_asset = symbol.split("/")[0]

    if action == "BUY":
        quantity = usdt_amount / market_price
        firebase_loesche_kaufpreise(base_asset, firebase_secret)
        if price_for_avg:
            try:
                firebase_speichere_kaufpreis(base_asset, float(price_for_avg), firebase_secret)
            except:
                return jsonify({"error": "Ungültiger Preiswert"}), 400
    else:
        quantity = 0

    result = send_futures_order(futures_symbol, quantity, action, api_key, secret_key)
    if result.get("code") != 0:
        return jsonify({"error": "Order fehlgeschlagen", "details": result}), 400

    position = get_futures_position(futures_symbol, api_key, secret_key)
    voll_menge = float(position["available_pos"] if position else 0)

    kaufpreise = firebase_hole_kaufpreise(base_asset, firebase_secret)
    avg_price = berechne_durchschnitt_preis(kaufpreise)

    limit_sell_price = avg_price * (1 + limit_sell_percent / 100) if avg_price > 0 and limit_sell_percent is not None else 0

    if voll_menge > 0 and limit_sell_price > 0:
        create_limit_futures_sell_order(futures_symbol, voll_menge, round(limit_sell_price, 4), api_key, secret_key)

    timestamp_berlin = datetime.now(ZoneInfo("Europe/Berlin")).strftime("%Y-%m-%d %H:%M:%S")

    firebase_speichere_trade_history({
        "timestamp": timestamp_berlin,
        "symbol": symbol,
        "action": action,
        "executed_price": market_price,
        "durchschnittspreis": avg_price,
        "quantity": quantity,
        "usdt_invested": round(quantity * market_price, 8),
        "limit_sell_percent": limit_sell_percent,
        "limit_sell_price": round(limit_sell_price, 4)
    }, firebase_secret)

    return jsonify({
        "symbol": symbol,
        "action": action,
        "executed_price": market_price,
        "durchschnittspreis": avg_price,
        "limit_sell_price": round(limit_sell_price, 4),
        "timestamp": timestamp_berlin
    })

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)

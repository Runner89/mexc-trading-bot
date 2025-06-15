import os
import time
import hmac
import hashlib
import requests
from flask import Flask, request, jsonify
from datetime import datetime

app = Flask(__name__)

BASE_URL = "https://api.mexc.com"

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
    timestamp = int(time.time() * 1000)
    params = f"timestamp={timestamp}"
    secret = os.environ.get("MEXC_SECRET_KEY", "")
    signature = hmac.new(secret.encode(), params.encode(), hashlib.sha256).hexdigest()
    url = f"{BASE_URL}/api/v3/account?{params}&signature={signature}"
    headers = {"X-MEXC-APIKEY": os.environ.get("MEXC_API_KEY", "")}
    res = requests.get(url, headers=headers)
    data = res.json()

    for item in data.get("balances", []):
        if item["asset"] == asset:
            return float(item.get("free", 0))
    return 0

def place_order(symbol, side, order_type, quantity=None, price=None):
    timestamp = int(time.time() * 1000)
    params = {
        "symbol": symbol,
        "side": side,
        "type": order_type,
        "timestamp": timestamp,
    }
    if quantity is not None:
        params["quantity"] = quantity
    if price is not None:
        params["price"] = price
        params["timeInForce"] = "GTC"  # Good-Till-Canceled für Limit-Order

    query = "&".join([f"{k}={v}" for k,v in sorted(params.items())])
    secret = os.environ.get("MEXC_SECRET_KEY", "")
    signature = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    url = f"{BASE_URL}/api/v3/order?{query}&signature={signature}"
    headers = {"X-MEXC-APIKEY": os.environ.get("MEXC_API_KEY", "")}
    response = requests.post(url, headers=headers)
    return response.json(), response.status_code

def cancel_open_limit_sell(symbol):
    # Hole offene Orders des Symbols und lösche Limit-Sell-Orders
    timestamp = int(time.time() * 1000)
    params = f"symbol={symbol}&timestamp={timestamp}"
    secret = os.environ.get("MEXC_SECRET_KEY", "")
    signature = hmac.new(secret.encode(), params.encode(), hashlib.sha256).hexdigest()
    url = f"{BASE_URL}/api/v3/openOrders?{params}&signature={signature}"
    headers = {"X-MEXC-APIKEY": os.environ.get("MEXC_API_KEY", "")}
    res = requests.get(url, headers=headers)
    data = res.json()

    # Falls Fehler
    if not isinstance(data, list):
        return data

    cancel_results = []
    for order in data:
        if order["side"] == "SELL" and order["type"] == "LIMIT":
            order_id = order["orderId"]
            cancel_params = f"symbol={symbol}&orderId={order_id}&timestamp={int(time.time() * 1000)}"
            cancel_signature = hmac.new(secret.encode(), cancel_params.encode(), hashlib.sha256).hexdigest()
            cancel_url = f"{BASE_URL}/api/v3/order?{cancel_params}&signature={cancel_signature}"
            cancel_resp = requests.delete(cancel_url, headers=headers)
            cancel_results.append(cancel_resp.json())
    return cancel_results

@app.route("/webhook", methods=["POST"])
def webhook():
    start_time = time.time()

    data = request.get_json()
    symbol = data.get("symbol")
    action = data.get("side", "BUY").upper()
    usdt_amount = data.get("usdt_amount")

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
        quantity = usdt_amount / price
        quantity = quantity - (quantity % step_size)
        quantity = round(quantity, 8)
        if quantity <= 0:
            return jsonify({"error": "Berechnete Menge ist 0 oder ungültig"}), 400

        # Market Buy ausführen
        buy_order, status = place_order(symbol, "BUY", "MARKET", quantity=quantity)
        if status != 200:
            return jsonify({"error": "Buy-Order fehlgeschlagen", "details": buy_order}), status

        # Durchschnittspreis aus der Buy Order nehmen (falls nicht verfügbar, fallback auf aktuellen Preis)
        avg_price = float(buy_order.get("price", price))

        # Limit Sell Preis = 1% über avg_price
        limit_sell_price = round(avg_price * 1.01, 8)

        # Vorherige Limit-Sell Orders löschen
        cancel_results = cancel_open_limit_sell(symbol)

        # Neue Limit-Sell-Order setzen mit gesamter Menge aus dem Buy
        limit_sell_order, sell_status = place_order(symbol, "SELL", "LIMIT", quantity=quantity, price=limit_sell_price)
        if sell_status != 200:
            return jsonify({"error": "Limit-Sell-Order fehlgeschlagen", "details": limit_sell_order}), sell_status

        response_time = (time.time() - start_time) * 1000
        buy_order["responseTime"] = f"{response_time:.2f} ms"
        buy_order["limitSellOrder"] = limit_sell_order
        buy_order["limitSellCancelResults"] = cancel_results
        buy_order["transactTimeReadable"] = datetime.fromtimestamp(buy_order.get("transactTime", 0) / 1000).strftime("%Y-%m-%d %H:%M:%S")

        return jsonify(buy_order), 200

    elif action == "SELL":
        # Market Sell: Ganze Position verkaufen
        quantity = get_balance(base_asset)
        quantity = quantity - (quantity % step_size)
        quantity = round(quantity, 8)

        if quantity <= 0:
            return jsonify({"error": f"Keine {base_asset}-Menge zum Verkaufen"}), 400

        sell_order, status = place_order(symbol, "SELL", "MARKET", quantity=quantity)
        if status != 200:
            return jsonify({"error": "Sell-Order fehlgeschlagen", "details": sell_order}), status

        response_time = (time.time() - start_time) * 1000
        sell_order["responseTime"] = f"{response_time:.2f} ms"
        sell_order["transactTimeReadable"] = datetime.fromtimestamp(sell_order.get("transactTime", 0) / 1000).strftime("%Y-%m-%d %H:%M:%S")

        return jsonify(sell_order), 200

    else:
        return jsonify({"error": "Ungültige Aktion. Nur BUY oder SELL erlaubt."}), 400

@app.route("/", methods=["GET"])
def home():
    return "✅ MEXC Webhook läuft!"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

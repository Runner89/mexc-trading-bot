from flask import Flask, request, jsonify
import time
import hmac
import hashlib
import requests
import os

app = Flask(__name__)

# --- BingX API ---
BASE_URL = "https://open-api.bingx.com"
BALANCE_ENDPOINT = "/openApi/swap/v2/user/balance"
ORDER_ENDPOINT = "/openApi/swap/v2/trade/order"
PRICE_ENDPOINT = "/openApi/swap/v2/quote/price"
OPEN_ORDERS_ENDPOINT = "/openApi/swap/v2/trade/openOrders"

# --- Firebase Setup ---
FIREBASE_URL = os.environ.get("FIREBASE_URL", "")  # z. B. https://deinprojekt.firebaseio.com

def generate_signature(secret_key: str, params: str) -> str:
    return hmac.new(secret_key.encode('utf-8'), params.encode('utf-8'), hashlib.sha256).hexdigest()

def get_futures_balance(api_key: str, secret_key: str):
    timestamp = int(time.time() * 1000)
    params = f"timestamp={timestamp}"
    signature = generate_signature(secret_key, params)
    url = f"{BASE_URL}{BALANCE_ENDPOINT}?{params}&signature={signature}"
    headers = {"X-BX-APIKEY": api_key}
    response = requests.get(url, headers=headers)
    return response.json()

def get_current_price(symbol: str):
    url = f"{BASE_URL}{PRICE_ENDPOINT}?symbol={symbol}"
    response = requests.get(url)
    data = response.json()
    if data.get("code") == 0 and "data" in data and "price" in data["data"]:
        return float(data["data"]["price"])
    else:
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

def place_limit_sell_order(api_key: str, secret_key: str, symbol: str, quantity: float, limit_price: float, position_side: str = "SHORT"):
    timestamp = int(time.time() * 1000)

    params_dict = {
        "symbol": symbol,
        "side": "SELL",
        "type": "LIMIT",
        "quantity": round(quantity, 6),
        "price": round(limit_price, 6),
        "timeInForce": "GTC",
        "positionSide": position_side,
        "timestamp": timestamp
    }

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

def get_open_orders(api_key: str, secret_key: str, symbol: str):
    timestamp = int(time.time() * 1000)
    params = f"symbol={symbol}&timestamp={timestamp}"
    signature = generate_signature(secret_key, params)
    url = f"{BASE_URL}{OPEN_ORDERS_ENDPOINT}?{params}&signature={signature}"
    headers = {"X-BX-APIKEY": api_key}
    response = requests.get(url, headers=headers)

    try:
        data = response.json()
    except ValueError:
        # Rückgabe bei ungültiger JSON-Antwort
        return {"code": -1, "msg": "Ungültige API-Antwort", "raw_response": response.text}

    return data


def cancel_order(api_key: str, secret_key: str, symbol: str, order_id: str):
    timestamp = int(time.time() * 1000)
    params = f"symbol={symbol}&orderId={order_id}&timestamp={timestamp}"
    signature = generate_signature(secret_key, params)
    url = f"{BASE_URL}{ORDER_ENDPOINT}?{params}&signature={signature}"
    headers = {"X-BX-APIKEY": api_key}
    response = requests.delete(url, headers=headers)
    return response.json()

def firebase_speichere_kaufpreis(asset, price, firebase_secret):
    url = f"{FIREBASE_URL}/kaufpreise/{asset}.json?auth={firebase_secret}"
    data = {"price": price}
    response = requests.post(url, json=data)
    # Wir geben den Status als log zurück
    return f"Kaufpreis gespeichert für {asset}: {price}, Status: {response.status_code}"

def firebase_lese_kaufpreise(asset, firebase_secret):
    url = f"{FIREBASE_URL}/kaufpreise/{asset}.json?auth={firebase_secret}"
    response = requests.get(url)
    if response.status_code != 200:
        return None

    data = response.json()
    if not data:
        return []

    return [eintrag.get("price") for eintrag in data.values() if isinstance(eintrag, dict) and "price" in eintrag]

def berechne_durchschnittspreis(preise: list):
    preise = [float(p) for p in preise if isinstance(p, (int, float, str)) and str(p).replace('.', '', 1).isdigit()]
    if not preise:
        return None
    return round(sum(preise) / len(preise), 4)

@app.route('/webhook', methods=['POST'])
def webhook():
    logs = []

    data = request.json
    sell_percentage = data.get("sell_percentage")

    api_key = data.get("api_key")
    secret_key = data.get("secret_key")
    symbol = data.get("symbol", "BTC-USDT")
    usdt_amount = data.get("usdt_amount")
    position_side = data.get("position_side") or data.get("positionSide") or "LONG"
    firebase_secret = data.get("FIREBASE_SECRET")
    price_from_webhook = data.get("price")

    if not api_key or not secret_key or not usdt_amount:
        return jsonify({"error": True, "msg": "api_key, secret_key and usdt_amount are required"}), 400

    logs.append(f"Starte Balance-Abfrage für {symbol}...")
    balance_response = get_futures_balance(api_key, secret_key)
    logs.append(f"Balance Antwort erhalten: {balance_response}")

    # === Market-Order platzieren ===
    logs.append(f"Plaziere Market-Order mit {usdt_amount} USDT für {symbol} ({position_side})...")
    order_response = place_market_order(api_key, secret_key, symbol, float(usdt_amount), position_side)
    logs.append(f"Market-Order Antwort: {order_response}")

# === Gekaufte Menge extrahieren ===
try:
    executed_qty = float(order_response["data"]["order"]["executedQty"])
    logs.append(f"[Market Order] Ausgeführte Menge: {executed_qty}")
except Exception as e:
    executed_qty = 0
    logs.append(f"[Market Order] Fehler beim Lesen der ausgeführten Menge: {e}")

# === Alte SELL-Orders stornieren (wenn vorhanden) ===
try:
    open_orders = get_open_orders(api_key, secret_key, symbol)
    logs.append(f"Open Orders Rohdaten: {open_orders} (Typ: {type(open_orders)})")
    if isinstance(open_orders, dict) and open_orders.get("code") == 0:
        for order in open_orders.get("data", {}).get("orders", []):
            if order.get("side") == "SELL" and order.get("positionSide") == "LONG":
                cancel_response = cancel_order(api_key, secret_key, symbol, str(order.get("orderId")))
                logs.append(f"Storniere Order {order.get('orderId')}: {cancel_response}")
    else:
        logs.append(f"Open Orders Antwort unerwartet: {open_orders}")
except Exception as e:
    logs.append(f"Fehler beim Abfragen oder Stornieren offener Orders: {e}")

# === Limit-Preis berechnen (z. B. 1.5x vom Market-Kaufpreis) ===
limit_price = round(float(price_from_webhook) * sell_percentage, 5)
logs.append(f"[Limit Order] Limit-Preis: {limit_price}, Verkaufsmenge (executedQty): {executed_qty}")

# === SELL-Limit-Order mit exakter Menge platzieren ===
try:
    limit_order_result = place_limit_order(
        api_key=api_key,
        secret_key=secret_key,
        symbol=symbol,
        quantity=executed_qty,
        price=limit_price,
        position_side="LONG"
    )
    logs.append(f"[Limit Order] Antwort: {limit_order_result}")
    logs.append("Limit-Order erfolgreich platziert!")
except Exception as e:
    limit_order_result = {"error": True, "msg": str(e)}
    logs.append(f"[Limit Order] Fehler: {e}")


    durchschnittspreis = None
    kaufpreise = []
    if firebase_secret:
        try:
            base_asset = symbol.split("-")[0]
            kaufpreise = firebase_lese_kaufpreise(base_asset, firebase_secret)
            if kaufpreise is None:
                logs.append(f"[Firebase] Fehler beim Abrufen der Kaufpreise")
                kaufpreise = []
            durchschnittspreis = berechne_durchschnittspreis(kaufpreise)
            logs.append(f"[Firebase] Durchschnittspreis berechnet: {durchschnittspreis}")
        except Exception as e:
            logs.append(f"[Firebase] Fehler beim Berechnen des Durchschnittspreises: {e}")

    limit_order_response = None

    if durchschnittspreis is not None and sell_percentage is not None and firebase_secret:
        try:
            limit_price = durchschnittspreis * (1 + float(sell_percentage) / 100)
            executed_qty = float(order_response.get("data", {}).get("order", {}).get("executedQty", 0))

            logs.append(f"[Limit Order] Limit-Preis: {limit_price}, Ausgeführte Menge: {executed_qty}")

            if executed_qty > 0:
                limit_order_response = place_limit_sell_order(
                    api_key, secret_key, symbol, executed_qty, limit_price, position_side="LONG"
                )
                logs.append(f"[Limit Order] Antwort: {limit_order_response}")

                if limit_order_response.get("code") != 0:
                    logs.append(f"Fehler bei Limit-Order: {limit_order_response.get('msg')}")
                else:
                    logs.append("Limit-Order erfolgreich platziert!")
            else:
                logs.append("[Limit Order] Keine ausgeführte Menge aus Market-Order gefunden, Limit-Order nicht platziert.")
        except Exception as e:
            logs.append(f"[Limit Order] Fehler beim Platzieren der Limit-Order: {e}")

    # Beispiel: offene Sell-Orders mit PositionSide LONG stornieren
    try:
        open_orders = get_open_orders(api_key, secret_key, symbol)
        logs.append(f"Open Orders Rohdaten: {open_orders} (Typ: {type(open_orders)})")
        if isinstance(open_orders, dict) and open_orders.get("code") == 0:
            for order in open_orders.get("data", {}).get("orders", []):
                if order.get("side") == "SELL" and order.get("positionSide") == "LONG":
                    cancel_response = cancel_order(api_key, secret_key, symbol, str(order.get("orderId")))
                    logs.append(f"Storniere Order {order.get('orderId')}: {cancel_response}")
        else:
            logs.append(f"Open Orders Antwort unerwartet oder Fehler: {open_orders}")
    except Exception as e:
        logs.append(f"Fehler beim Abfragen oder Stornieren offener Orders: {e}")

    return jsonify({
        "error": False,
        "available_balances": balance_response.get("data", {}).get("balance", {}),
        "order_result": order_response,
        "limit_order_result": limit_order_response,
        "order_params": {
            "symbol": symbol,
            "usdt_amount": usdt_amount,
            "position_side": position_side,
            "price_from_webhook": price_from_webhook,
            "sell_percentage": sell_percentage
        },
        "firebase_average_price": durchschnittspreis,
        "firebase_all_prices": kaufpreise,
        "logs": logs
    })

# --- Flask App Start ---
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)

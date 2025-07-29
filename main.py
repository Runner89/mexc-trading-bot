#Limit order wird gelöscht und gesetzt, aber nicht mit der richtigen Menge

from flask import Flask, request, jsonify
import time
import hmac
import hashlib
import requests
import os

app = Flask(__name__)

BASE_URL = "https://open-api.bingx.com"
BALANCE_ENDPOINT = "/openApi/swap/v2/user/balance"
ORDER_ENDPOINT = "/openApi/swap/v2/trade/order"
PRICE_ENDPOINT = "/openApi/swap/v2/quote/price"
OPEN_ORDERS_ENDPOINT = "/openApi/swap/v2/trade/openOrders"

FIREBASE_URL = os.environ.get("FIREBASE_URL", "")

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

def place_market_order(api_key, secret_key, symbol, usdt_amount, position_side="LONG"):
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

def send_signed_request(http_method, endpoint, api_key, secret_key, params=None):
    import requests
    import time
    import hmac
    import hashlib

    if params is None:
        params = {}

    timestamp = int(time.time() * 1000)
    params['timestamp'] = timestamp

    query_string = "&".join(f"{k}={params[k]}" for k in sorted(params))
    signature = hmac.new(secret_key.encode(), query_string.encode(), hashlib.sha256).hexdigest()
    params['signature'] = signature

    url = f"{BASE_URL}{endpoint}"

    headers = {
        "X-BX-APIKEY": api_key
    }

    if http_method == "GET":
        response = requests.get(url, headers=headers, params=params)
    elif http_method == "POST":
        response = requests.post(url, headers=headers, json=params)
    elif http_method == "DELETE":
        response = requests.delete(url, headers=headers, params=params)
    else:
        raise ValueError("Unsupported HTTP method")

    return response.json()


def get_current_position(api_key, secret_key, symbol, position_side, logs=None):
    endpoint = "/openApi/swap/v2/user/positions"
    params = {"symbol": symbol}
    response = send_signed_request("GET", endpoint, api_key, secret_key, params)

    positions = response.get("data", [])
    raw_positions = positions if isinstance(positions, list) else []

    if logs is not None:
        logs.append(f"Positions Rohdaten: {raw_positions}")

    position_size = 0
    if response.get("code") == 0:
        for pos in positions:
            if pos.get("symbol") == symbol and pos.get("positionSide", "").upper() == position_side.upper():
                if logs is not None:
                    logs.append(f"Gefundene Position: {pos}")
                try:
                    # Versuche verschiedene Felder
                    position_size = float(pos.get("size", 0))
                    if position_size == 0:
                        position_size = float(pos.get("positionAmt", 0))
                    if logs is not None:
                        logs.append(f"Position size ermittelt: {position_size}")
                except (ValueError, TypeError) as e:
                    position_size = 0
                    if logs is not None:
                        logs.append(f"Fehler beim Parsen der Positionsgröße: {e}")
                break

    else:
        if logs is not None:
            logs.append(f"API Antwort Fehlercode: {response.get('code')}")

    return position_size, raw_positions




def place_limit_sell_order(api_key, secret_key, symbol, quantity, limit_price, position_side="LONG"):
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

def get_open_orders(api_key, secret_key, symbol):
    timestamp = int(time.time() * 1000)
    params = f"symbol={symbol}&timestamp={timestamp}"
    signature = generate_signature(secret_key, params)
    url = f"{BASE_URL}{OPEN_ORDERS_ENDPOINT}?{params}&signature={signature}"
    headers = {"X-BX-APIKEY": api_key}
    response = requests.get(url, headers=headers)

    try:
        data = response.json()
    except ValueError:
        return {"code": -1, "msg": "Ungültige API-Antwort", "raw_response": response.text}

    return data

def cancel_order(api_key, secret_key, symbol, order_id):
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

def berechne_durchschnittspreis(preise):
    preise = [float(p) for p in preise if isinstance(p, (int, float, str)) and str(p).replace('.', '', 1).isdigit()]
    return round(sum(preise) / len(preise), 4) if preise else None

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

    logs.append(f"Plaziere Market-Order mit {usdt_amount} USDT für {symbol} ({position_side})...")
    order_response = place_market_order(api_key, secret_key, symbol, float(usdt_amount), position_side)
    
    # Warte 2 Sekunden, um Positionsdaten zu aktualisieren
    time.sleep(2)
    logs.append(f"Market-Order Antwort: {order_response}")

    if firebase_secret and price_from_webhook:
        try:
            base_asset = symbol.split("-")[0]
            firebase_save_result = firebase_speichere_kaufpreis(base_asset, float(price_from_webhook), firebase_secret)
            logs.append(f"[Firebase] Webhook-Preis gespeichert: {firebase_save_result}")
        except Exception as e:
            logs.append(f"[Firebase] Fehler beim Speichern des Webhook-Preises: {e}")

    try:
        sell_quantity, positions_raw = get_current_position(api_key, secret_key, symbol, position_side, logs)
        logs.append(f"[Market Order] Ausgeführte Menge (Position Size): {sell_quantity}")


        # Falls kein Positionssize zurückkommt, Menge aus Market-Order nutzen
        if sell_quantity == 0:
            executed_qty_str = order_response.get("data", {}).get("order", {}).get("executedQty")
            if executed_qty_str:
                sell_quantity = float(executed_qty_str)
                logs.append(f"[Market Order] Ausgeführte Menge aus order_response genutzt: {sell_quantity}")

    except Exception as e:
        sell_quantity = 0
        logs.append(f"[Market Order] Fehler beim Lesen der Positionsgröße: {e}")



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

    limit_order_response = None
    durchschnittspreis = None
    kaufpreise = []

    if firebase_secret:
        try:
            base_asset = symbol.split("-")[0]
            kaufpreise = firebase_lese_kaufpreise(base_asset, firebase_secret)
            durchschnittspreis = berechne_durchschnittspreis(kaufpreise or [])
            logs.append(f"[Firebase] Durchschnittspreis berechnet: {durchschnittspreis}")
        except Exception as e:
            logs.append(f"[Firebase] Fehler beim Berechnen des Durchschnittspreises: {e}")

    try:
        if durchschnittspreis and sell_percentage:
            limit_price = round(durchschnittspreis * (1 + float(sell_percentage) / 100), 5)
            logs.append(f"[Limit Order] Limit-Preis auf Basis von Firebase-Durchschnitt {durchschnittspreis} + {sell_percentage}%: {limit_price}")
        else:
            limit_price = 0
            logs.append(f"[Limit Order] Kein Durchschnittspreis oder Prozentsatz vorhanden – Limit-Order wird nicht gesetzt.")

        logs.append(f"[Limit Order] Limit-Preis: {limit_price}, Verkaufsmenge: {sell_quantity}")

        if sell_quantity > 0 and limit_price > 0:
            limit_order_response = place_limit_sell_order(api_key, secret_key, symbol, sell_quantity, limit_price, position_side="LONG")
            logs.append(f"[Limit Order] Antwort: {limit_order_response}")
        else:
            logs.append("[Limit Order] Ungültige Orderdaten, Limit-Order nicht gesendet.")
    except Exception as e:
        logs.append(f"[Limit Order] Fehler beim Platzieren: {e}")

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

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)

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

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

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

def place_market_order(api_key, secret_key, symbol, margin_amount, position_side="LONG"):
    price = get_current_price(symbol)
    if price is None:
        return {"code": 99999, "msg": "Failed to get current price"}

    # Coin-Menge aus Margin * Leverage berechnen
    quantity = margin_amount / price
    quantity = round(quantity, 6)

    timestamp = int(time.time() * 1000)
    side = "BUY" if position_side.upper() == "LONG" else "SELL"

    params_dict = {
        "symbol": symbol,
        "side": side,
        "type": "MARKET",
        "quantity": quantity,
        "positionSide": position_side.upper(),
        "timestamp": timestamp
    }

    query_string = "&".join(f"{k}={params_dict[k]}" for k in sorted(params_dict))
    signature = generate_signature(secret_key, query_string)
    params_dict["signature"] = signature

    url = f"{BASE_URL}{ORDER_ENDPOINT}"
    headers = {"X-BX-APIKEY": api_key, "Content-Type": "application/json"}

    response = requests.post(url, headers=headers, json=params_dict)
    return response.json()

def send_signed_request(http_method, endpoint, api_key, secret_key, params=None):
    if params is None:
        params = {}

    timestamp = int(time.time() * 1000)
    params['timestamp'] = timestamp

    query_string = "&".join(f"{k}={params[k]}" for k in sorted(params))
    signature = hmac.new(secret_key.encode(), query_string.encode(), hashlib.sha256).hexdigest()
    params['signature'] = signature

    url = f"{BASE_URL}{endpoint}"
    headers = {"X-BX-APIKEY": api_key}

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

    position_size = 0
    liquidation_price = None
    entry_price = 0

    if response.get("code") == 0:
        for pos in positions:
            if pos.get("symbol") == symbol and pos.get("positionSide", "").upper() == position_side.upper():
                position_size = float(pos.get("size", 0)) or float(pos.get("positionAmt", 0))
                entry_price = float(pos.get("avgPrice", 0))  # <— Hier richtiges Feld
                break
        
        return position_size, raw_positions, entry_price


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
    headers = {"X-BX-APIKEY": api_key, "Content-Type": "application/json"}
    response = requests.post(url, headers=headers, json=params_dict)
    return response.json()

def set_leverage(api_key, secret_key, symbol, leverage, position_side="LONG"):
    endpoint = "/openApi/swap/v2/trade/leverage"
    side_map = {"LONG": "BUY", "SHORT": "SELL"}
    params = {
        "symbol": symbol,
        "leverage": int(leverage),
        "positionSide": position_side.upper(),
        "side": side_map.get(position_side.upper())
    }
    return send_signed_request("POST", endpoint, api_key, secret_key, params)

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    logs = []

    symbol = data.get("RENDER", {}).get("symbol")
    api_key = data.get("RENDER", {}).get("api_key")
    secret_key = data.get("RENDER", {}).get("secret_key")
    leverage = float(data.get("RENDER", {}).get("leverage", 1))
    sl_percent = float(data.get("RENDER", {}).get("sl_percent", 2))
    tp_percent = float(data.get("RENDER", {}).get("tp_percent", 1))
    position_side = data.get("RENDER", {}).get("position_side", "LONG").upper()

    if not symbol or not api_key or not secret_key:
        return jsonify({"error": True, "msg": "symbol, api_key und secret_key sind erforderlich"}), 400

    try:
        # 1. verfügbare Margin abfragen
        balance_resp = get_futures_balance(api_key, secret_key)
        available_margin = float(balance_resp.get("data", {}).get("balance", {}).get("availableMargin", 0))
        logs.append(f"Available Margin: {available_margin}")

        # 2. Hebel setzen
        set_leverage(api_key, secret_key, symbol, leverage, position_side)
        logs.append(f"Leverage auf {leverage} gesetzt")
        time.sleep(1)

        # 3. Sicherheits-Puffer abziehen
        usable_margin = available_margin * 0.98
        logs.append(f"Usable Margin nach Sicherheits-Puffer ({(1-0.98)*100:.0f}%): {usable_margin}")

        # 4. Preis abfragen
        price = get_current_price(symbol)
        if not price:
            return jsonify({"error": True, "msg": "Preis konnte nicht abgefragt werden", "logs": logs}), 500

        # 5. Coin-Menge berechnen
        quantity = round((usable_margin * leverage) / price, 6)
        logs.append(f"Market Order Menge (Coin) = {quantity}")

               # Market Order
        order_resp = place_market_order(api_key, secret_key, symbol, usable_margin * leverage, position_side)
        logs.append(f"Market Order Response: {order_resp}")
        if order_resp.get("code") != 0:
            return jsonify({"error": True, "msg": f"Market Order fehlgeschlagen: {order_resp.get('msg')}", "logs": logs}), 500

        # Entry Price & Positionsgröße direkt aus Response
        entry_price = float(order_resp["data"]["order"]["avgPrice"])
        pos_size = float(order_resp["data"]["order"]["executedQty"])
        logs.append(f"Einstiegspreis: {entry_price}, Positionsgröße: {pos_size}")

        # SL & TP berechnen
        if position_side == "LONG":
            sl_price = round(entry_price * (1 - sl_percent / 100), 6)
            tp_price = round(entry_price * (1 + tp_percent / 100), 6)
            sl_side = tp_side = "SELL"
        else:
            sl_price = round(entry_price * (1 + sl_percent / 100), 6)
            tp_price = round(entry_price * (1 - tp_percent / 100), 6)
            sl_side = tp_side = "BUY"

        # Limit Orders setzen
        sl_order = place_limit_order(api_key, secret_key, symbol, pos_size, sl_price, sl_side, position_side)
        tp_order = place_limit_order(api_key, secret_key, symbol, pos_size, tp_price, tp_side, position_side)

        logs.append(f"SL Order: {sl_order}, TP Order: {tp_order}")

        return jsonify({
            "error": False,
            "status": "position_opened",
            "symbol": symbol,
            "entry_price": entry_price,
            "position_size": pos_size,
            "sl_price": sl_price,
            "tp_price": tp_price,
            "logs": logs
        })

    except Exception as e:
        return jsonify({"error": True, "msg": str(e), "logs": logs}), 500

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)

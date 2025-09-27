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

    if response.get("code") == 0:
        for pos in positions:
            if pos.get("symbol") == symbol and pos.get("positionSide", "").upper() == position_side.upper():
                try:
                    position_size = float(pos.get("size", 0)) or float(pos.get("positionAmt", 0))
                    liquidation_price = float(pos.get("liquidationPrice", 0))
                except (ValueError, TypeError):
                    position_size = 0
                break

    return position_size, raw_positions, liquidation_price

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

    symbol = data.get("RENDER", {}).get("symbol", "BTC-USDT")
    api_key = data.get("RENDER", {}).get("api_key")
    secret_key = data.get("RENDER", {}).get("secret_key")
    leverage = float(data.get("RENDER", {}).get("leverage", 1))
    sl_percent = float(data.get("RENDER", {}).get("sl_percent", 2))  # Stop Loss %
    tp_percent = float(data.get("RENDER", {}).get("tp_percent", 1))  # Take Profit %

    if not api_key or not secret_key:
        return jsonify({"error": True, "msg": "api_key und secret_key sind erforderlich"}), 400

    try:
        # 1. Guthaben abfragen
        balance_response = get_futures_balance(api_key, secret_key)
        available_usdt = float(balance_response.get("data", {}).get("balance", {}).get("availableMargin", 0))
        logs.append(f"Available USDT (Margin): {available_usdt}")

        # 2. Hebel setzen
        set_leverage(api_key, secret_key, symbol, leverage, "SHORT")
        logs.append(f"Leverage auf {leverage} gesetzt")

        # 3. Market Order mit kompletter verfügbaren Margin (bereits Hebel berücksichtigt)
        order_size = available_usdt
        logs.append(f"Ordergröße = Available USDT (Margin bereits Hebel berücksichtigt): {order_size}")

        order_response = place_market_order(api_key, secret_key, symbol, order_size, "SHORT")
        logs.append(f"Market SHORT Order: {order_response}")

        if order_response.get("code") != 0:
            logs.append(f"Fehler beim Order platzieren: {order_response.get('msg')}")
            return jsonify({
                "error": True,
                "msg": f"Market Order konnte nicht gesetzt werden: {order_response.get('msg')}",
                "logs": logs
            }), 500

        time.sleep(2)

        # Einstiegspreis bestimmen
        entry_price = None
        pos_size, positions_raw, _ = get_current_position(api_key, secret_key, symbol, "SHORT", logs)
        for pos in positions_raw:
            if pos.get("symbol") == symbol and pos.get("positionSide", "").upper() == "SHORT":
                entry_price = float(pos.get("avgPrice", 0))
                break

        if not entry_price:
            return jsonify({"error": True, "msg": "Kein Einstiegspreis ermittelt"}), 500

        logs.append(f"Einstiegspreis: {entry_price}, Positionsgröße: {pos_size}")

        # 4. SL & TP Preise berechnen
        sl_price = round(entry_price * (1 + sl_percent / 100), 6)
        tp_price = round(entry_price * (1 - tp_percent / 100), 6)

        logs.append(f"Stop Loss: {sl_price}, Take Profit: {tp_price}")

        # 5. Limit Orders setzen
        sl_order = place_limit_sell_order(api_key, secret_key, symbol, pos_size, sl_price, "SHORT")
        tp_order = place_limit_sell_order(api_key, secret_key, symbol, pos_size, tp_price, "SHORT")

        logs.append(f"SL Order: {sl_order}, TP Order: {tp_order}")

        return jsonify({
            "error": False,
            "status": "short_opened",
            "symbol": symbol,
            "entry_price": entry_price,
            "sl_price": sl_price,
            "tp_price": tp_price,
            "position_size": pos_size,
            "logs": logs
        })

    except Exception as e:
        return jsonify({"error": True, "msg": str(e), "logs": logs}), 500


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)


# NUR FUER SHORT POSITIONEN

# Wird die Order nicht ausgeführt, kommt eine Telegramm-Nachricht
# Wird SL und/oder TP nicht gesetzt, kommt eine Telegramm-Nachricht und die Position wird geschlossen.


#{
#  "RENDER": {
#    "symbol": "PUMP-USDT",
#    "api_key": "xxx",
#    "secret_key": "xxxx",
#    "position_side": "SHORT",
#    "leverage": 2,
#    "sl_percent": 0.9,
#    "tp_percent": 1.2
#  }
#}





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


def sende_telegram_nachricht(botname, text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return "Telegram nicht konfiguriert"
    full_text = f"[{botname}] {text}"
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": full_text}
    response = requests.post(url, json=payload)
    return f"Telegram Antwort: {response.status_code}"

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

def close_all_positions(api_key, secret_key):
    logs = []
    endpoint = "/openApi/swap/v2/user/positions"
    response = send_signed_request("GET", endpoint, api_key, secret_key, {})

    if response.get("code") != 0:
        return {"error": True, "msg": "Konnte Positionen nicht abfragen", "logs": [response]}

    positions = response.get("data", [])
    closed_positions = []

    for pos in positions:
        try:
            symbol = pos.get("symbol")
            position_side = pos.get("positionSide", "").upper()
            amt = float(pos.get("positionAmt", 0))

            if amt == 0:
                continue  # keine offene Position

            # Position schließen (immer Market)
            side = "SELL" if amt > 0 else "BUY"  # LONG schließen mit SELL, SHORT schließen mit BUY
            qty = abs(amt)

            timestamp = int(time.time() * 1000)
            params_dict = {
                "symbol": symbol,
                "side": side,
                "type": "MARKET",
                "quantity": round(qty, 6),
                "positionSide": position_side,
                "timestamp": timestamp
            }

            query_string = "&".join(f"{k}={params_dict[k]}" for k in sorted(params_dict))
            signature = generate_signature(secret_key, query_string)
            params_dict["signature"] = signature

            url = f"{BASE_URL}{ORDER_ENDPOINT}"
            headers = {"X-BX-APIKEY": api_key, "Content-Type": "application/json"}
            resp = requests.post(url, headers=headers, json=params_dict).json()

            logs.append(f"Closed {symbol} {position_side} ({qty}) → {resp}")
            closed_positions.append({
                "symbol": symbol,
                "side": position_side,
                "quantity": qty,
                "response": resp
            })

        except Exception as e:
            logs.append(f"Fehler beim Schließen von {pos}: {str(e)}")

    return {"error": False, "closed": closed_positions, "logs": logs}


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
        "side": "BUY",
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

def place_stoploss_order(api_key, secret_key, symbol, quantity, stop_price, position_side="SHORT"):
 
    timestamp = int(time.time() * 1000)
    params_dict = {
        "symbol": symbol,
        "side": "BUY",  # Short schließen
        "type": "STOP_MARKET",
        "quantity": round(quantity, 6),
        "stopPrice": round(stop_price, 6),
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
    position_side = data.get("RENDER", {}).get("position_side", "LONG").upper()
    tp_percent = float(data.get("RENDER", {}).get("tp_percent", 1))  
    sl_percent = float(data.get("RENDER", {}).get("sl_percent", 1)) 
    action = data.get("vyn", {}).get("action", "").lower()  

    if not symbol or not api_key or not secret_key:
        return jsonify({"error": True, "msg": "symbol, api_key und secret_key sind erforderlich"}), 400

    # nur bei einer Base Order, soll die SHORT-Position ausgefuehrt werden
    if action == "":
        close_resp = close_all_positions(api_key, secret_key, symbol, position_side)
        logs.append(f"Position sofort geschlossen: {close_resp}")

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
            logs.append(f"Usable Margin nach Sicherheits-Puffer (2%): {usable_margin}")
    
            # 4. Preis abfragen
            price = get_current_price(symbol)
            if not price:
                return jsonify({"error": True, "msg": "Preis konnte nicht abgefragt werden", "logs": logs}), 500
    
            # 5. Coin-Menge berechnen
            quantity = round((usable_margin * leverage) / price, 6)
            logs.append(f"Market Order Menge (Coin) = {quantity}")
    
            # 6. Market Order platzieren
            order_resp = place_market_order(api_key, secret_key, symbol, usable_margin * leverage, position_side)
            logs.append(f"Market Order Response: {order_resp}")
            time.sleep(1)        
            # Prüfen, ob die Order gefüllt wurde
            order_status = order_resp.get("data", {}).get("order", {}).get("status")
            if order_resp.get("code") != 0 or order_status != "FILLED":
                # Telegram senden, da keine Position eröffnet wurde
                message = f"⚠️ Position konnte nicht eröffnet werden!\nSymbol: {symbol}\nResponse: {order_resp}"
                sende_telegram_nachricht("BingX Bot", message)
                logs.append("Telegram-Nachricht gesendet: Position konnte nicht eröffnet werden")
            
                return jsonify({
                    "error": True,
                    "msg": "Market Order konnte nicht gefüllt werden, keine Position eröffnet",
                    "logs": logs
                }), 500
            
            # 6b. Positionsdaten direkt abfragen, um den echten Entry Price zu bekommen
            time.sleep(1)  # kurze Wartezeit, bis Order vollständig gefüllt ist
            
            # Entry Price und Position Size direkt aus Order-Response lesen
            order_data = order_resp.get("data", {}).get("order", {})
            entry_price = float(order_data.get("avgPrice", 0))
            pos_size = float(order_data.get("executedQty", 0))
    
            logs.append(f"Entry Price (avgPrice): {entry_price}")
            logs.append(f"Position Size: {pos_size}")
    
            
            # TP und SL nur setzen, wenn Position erfolgreich eröffnet wurde
            if pos_size <= 0:
                message = f"⚠️ Position wurde nicht eröffnet, daher keine TP/SL gesetzt.\nSymbol: {symbol}"
                sende_telegram_nachricht("BingX Bot", message)
                logs.append("Telegram-Nachricht gesendet: Keine TP/SL gesetzt")
                return jsonify({
                    "error": True,
                    "msg": "Position konnte nicht eröffnet werden, TP/SL nicht gesetzt",
                    "logs": logs
                }), 500
    
            # TP und SL berechnen
            if position_side.upper() == "SHORT":
                tp_price = round(entry_price * (1 - tp_percent / 100), 6)
                sl_price = round(entry_price * (1 + sl_percent / 100), 6)
            else:  # Optional für Long
                tp_price = round(entry_price * (1 + tp_percent / 100), 6)
                sl_price = round(entry_price * (1 - sl_percent / 100), 6)
                
            # 7. TP Limit-Order setzen
            tp_price = round(entry_price * (1 + tp_percent / 100 if position_side == "LONG" else 1 - tp_percent / 100), 6)
            tp_order_resp = place_limit_sell_order(api_key, secret_key, symbol, pos_size, tp_price, position_side)
            logs.append(f"TP Limit Order gesetzt @ {tp_price}: {tp_order_resp}")
            
            # Prüfen, ob TP gesetzt wurde
            if tp_order_resp.get("code") != 0 or tp_order_resp.get("data", {}).get("order", {}).get("status") != "NEW":
                message = f"⚠️ TP Limit-Order konnte nicht gesetzt werden!\nSymbol: {symbol}\nResponse: {tp_order_resp}"
                sende_telegram_nachricht("BingX Bot", message)
                logs.append("Telegram-Nachricht gesendet: TP Limit-Order konnte nicht gesetzt werden")
            
            # 8. SL Stop-Market-Order setzen
            sl_price = round(entry_price * (1 - sl_percent / 100 if position_side == "LONG" else 1 + sl_percent / 100), 6)
            sl_order_resp = place_stoploss_order(api_key, secret_key, symbol, pos_size, sl_price, position_side)
            logs.append(f"SL Stop-Market Order gesetzt @ {sl_price}: {sl_order_resp}")
            
            # Prüfen, ob SL gesetzt wurde
            if sl_order_resp.get("code") != 0 or sl_order_resp.get("data", {}).get("order", {}).get("status") != "NEW":
                message = f"⚠️ SL Stop-Market-Order konnte nicht gesetzt werden!\nSymbol: {symbol}\nResponse: {sl_order_resp}"
                sende_telegram_nachricht("BingX Bot", message)
                logs.append("Telegram-Nachricht gesendet: SL Stop-Market-Order konnte nicht gesetzt werden")
    
             # Wenn TP oder SL nicht gesetzt werden konnten Position schliessen
            if tp_order_resp.get("code") != 0 or tp_order_resp.get("data", {}).get("order", {}).get("status") != "NEW" \
                or sl_order_resp.get("code") != 0 or sl_order_resp.get("data", {}).get("order", {}).get("status") != "NEW":
            
                # Telegram senden
                message = f"⚠️ TP oder SL konnte nicht gesetzt werden. Schließe Position sofort!\nSymbol: {symbol}"
                sende_telegram_nachricht("BingX Bot", message)
            
                # Offene Position sofort schließen
                close_resp = close_all_positions(api_key, secret_key)
                logs.append(f"Position sofort geschlossen: {close_resp}")
            
                return jsonify({
                    "error": True,
                    "msg": "TP/SL konnte nicht gesetzt werden. Position wurde geschlossen.",
                    "logs": logs
                }), 500
    
            return jsonify({
                "error": False,
                "status": "position_opened",
                "symbol": symbol,
                "entry_price": entry_price,
                "position_size": pos_size,
                "tp_price": tp_price,
                "sl_price": sl_price,
                "logs": logs
            })
    
        except Exception as e:
            return jsonify({"error": True, "msg": str(e), "logs": logs}), 500

        
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)

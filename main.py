#vyn
#Market Order mit Hebel wird gesetzt
#Hebel muss in BINGX selber vorher eingestellt werden
#Preis, welcher im JSON übergeben wurde, wird in Firebase gespeichert
#Durschnittspreis wird von Firebase berechnet und entsprechend die Sell-Limit Order gesetzt
#Bei Alarm wird angegeben, ab welcher SO ein Alarm via Telegramm gesendet wird
#Verfügbares Guthaben wird ermittelt
#Ordergrösse = (Verfügbares Guthaben - Sicherheit)/Pyramiding
#Ordergrösse wird in Variable gespeichert, Firebase wird nur als Backup verwendet
#StopLoss 3% über Liquidationspreis
#Falls Firebaseverbindung fehlschlägt, wird der Durchschnittspreis aus Bingx -0.3% für die Berechnung der Sell-Limit-Order verwendet.
#Falls Status Fehler werden für den Alarm nicht die Anzahl Kaufpreise gezählt, sondern von der Variablen alarm_counter

###### Funktioniert nur, wenn alle Order die gleiche Grösse haben (Durchschnittspreis stimmt sonst nicht in Firebase) #####

#https://......../webhook
#{
#    "api_key": "",
#    "secret_key": "",
#    "symbol": "BABY-USDT",
#    "botname": "Baby_Bot", # muss einmalig sein
#    "position_side": "LONG",
#    "sell_percentage": 2.5,
#    "price": 0.068186,
#    "leverage": 1,
#    "FIREBASE_SECRET": "",
#    "alarm": 1,
#    "pyramiding": 8,
#    "sicherheit": 96 Sicherheit muss nicht mal Hebel gerechnet werden, wird im Code gemacht
#}
#    Berechnung Ordergrösse
#    verfügbares Guthaben x leverage
#    - (Sicherheit x leverage)
#    Eregbnis / pyramiding


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

saved_usdt_amounts = {}  # globales Dict für alle Coins
status_fuer_alle = {} 
alarm_counter = {}

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
    headers = {
        "X-BX-APIKEY": api_key,
        "Content-Type": "application/json"
    }

    response = requests.post(url, headers=headers, json=params_dict)
    return response.json()

def place_stop_loss_order(api_key, secret_key, symbol, quantity, stop_price, position_side="LONG"):
    timestamp = int(time.time() * 1000)

    params_dict = {
        "symbol": symbol,
        "side": "SELL",
        "type": "STOP_MARKET",
        "stopPrice": round(stop_price, 6),
        "quantity": round(quantity, 6),
        "positionSide": position_side,
        "timestamp": timestamp,
        "timeInForce": "GTC"
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

    if logs is not None:
        logs.append(f"Positions Rohdaten: {raw_positions}")

    position_size = 0
    liquidation_price = None

    if response.get("code") == 0:
        for pos in positions:
            if pos.get("symbol") == symbol and pos.get("positionSide", "").upper() == position_side.upper():
                if logs is not None:
                    logs.append(f"Gefundene Position: {pos}")
                try:
                    position_size = float(pos.get("size", 0)) or float(pos.get("positionAmt", 0))
                    liquidation_price = float(pos.get("liquidationPrice", 0))
                    if logs is not None:
                        logs.append(f"Position size: {position_size}, Liquidation price: {liquidation_price}")
                except (ValueError, TypeError) as e:
                    position_size = 0
                    if logs is not None:
                        logs.append(f"Fehler beim Parsen: {e}")
                break
    else:
        if logs is not None:
            logs.append(f"API Antwort Fehlercode: {response.get('code')}")

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
    headers = {
        "X-BX-APIKEY": api_key,
        "Content-Type": "application/json"
    }

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

# --- Firebase Funktionen jetzt mit botname statt asset ---
def firebase_speichere_ordergroesse(botname, betrag, firebase_secret):
    url = f"{FIREBASE_URL}/ordergroesse/{botname}.json?auth={firebase_secret}"
    data = {"usdt_amount": betrag}
    response = requests.put(url, json=data)
    return f"Ordergröße für {botname} gespeichert: {betrag}, Status: {response.status_code}"

def firebase_lese_ordergroesse(botname, firebase_secret):
    url = f"{FIREBASE_URL}/ordergroesse/{botname}.json?auth={firebase_secret}"
    response = requests.get(url)
    if response.status_code != 200:
        return None
    try:
        data = response.json()
        if isinstance(data, dict) and "usdt_amount" in data:
            return float(data["usdt_amount"])
        elif isinstance(data, (int, float)):
            return float(data)
    except Exception as e:
        print(f"[Fehler] Firebase JSON Parsing: {e}")
    return None

def firebase_loesche_ordergroesse(botname, firebase_secret):
    url = f"{FIREBASE_URL}/ordergroesse/{botname}.json?auth={firebase_secret}"
    response = requests.delete(url)
    return f"Ordergröße für {botname} gelöscht, Status: {response.status_code}"

def firebase_speichere_kaufpreis(botname, price, firebase_secret):
    url = f"{FIREBASE_URL}/kaufpreise/{botname}.json?auth={firebase_secret}"
    data = {"price": price}
    response = requests.post(url, json=data)
    return f"Kaufpreis gespeichert für {botname}: {price}, Status: {response.status_code}"

def firebase_loesche_kaufpreise(botname, firebase_secret):
    url = f"{FIREBASE_URL}/kaufpreise/{botname}.json?auth={firebase_secret}"
    response = requests.delete(url)
    if response.status_code == 200:
        return f"Kaufpreise für {botname} gelöscht."
    return f"Fehler beim Löschen der Kaufpreise für {botname}: Status {response.status_code}"

def firebase_lese_kaufpreise(botname, firebase_secret):
    url = f"{FIREBASE_URL}/kaufpreise/{botname}.json?auth={firebase_secret}"
    response = requests.get(url)
    if response.status_code != 200:
        return []
    data = response.json()
    if not data:
        return []
    return [eintrag.get("price") for eintrag in data.values() if isinstance(eintrag, dict) and "price" in eintrag]


def berechne_durchschnittspreis(preise):
    preise = [float(p) for p in preise if isinstance(p, (int, float, str)) and str(p).replace('.', '', 1).isdigit()]
    return round(sum(preise) / len(preise), 6) if preise else None

def set_leverage(api_key, secret_key, symbol, leverage, position_side="LONG"):
    endpoint = "/openApi/swap/v2/trade/leverage"
    
    # mappe positionSide auf side für Hebel-Setzung
    side_map = {
        "LONG": "BUY",
        "SHORT": "SELL"
    }
    
    params = {
        "symbol": symbol,
        "leverage": int(leverage),
        "positionSide": position_side.upper(),
        "side": side_map.get(position_side.upper())  # korrektes Side-Value setzen
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

    # Prüfen, ob action vorhanden ist (vyn.action oder action)
    action = data.get("vyn", {}).get("action") or data.get("action")
    if action:
        return jsonify({"status": "ignored", "reason": "action vorhanden"}), 200

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
        
        # 3. Market Order mit kompletter verfügbaren Margin
        order_size = available_usdt * leverage
        logs.append(f"Ordergröße = Available USDT x Leverage: {order_size}")
        
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

        logs.append(f"Stop Loss Price: {sl_price}")
        logs.append(f"Take Profit Price: {tp_price}")

        # 5. Limit Orders setzen
        sl_order = place_limit_sell_order(api_key, secret_key, symbol, pos_size, sl_price, "SHORT")
        tp_order = place_limit_sell_order(api_key, secret_key, symbol, pos_size, tp_price, "SHORT")

        logs.append(f"SL Order: {sl_order}")
        logs.append(f"TP Order: {tp_order}")

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

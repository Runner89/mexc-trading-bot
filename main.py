#Market Order mit Hebel wird gesetzt
#Hebel muss in Bingx selber vorher eingestellt werden
#Preis, welcher im JSON übergeben wurde, wird in Firebase gespeichert
#Durschnittspreis wird von Firebase berechnet und entsprechend die Sell-Limit Order gesetzt
#Bei Alarm wird angegeben, ab welcher SO ein Alarm via Telegramm gesendet wird
#Verfügbares Guthaben wird ermittelt
#Ordergröss = (Verfügbares Guthaben - Sicherheit)/Pyramiding

###### Funktioniert nur, wenn alle Order die gleiche Grösse haben (Durchschnittspreis stimmt sonst nicht in Firebase) #####

#https://test1-0zfh.onrender.com/webhook
#{
#    "api_key": "",
#    "secret_key": "",
#    "symbol": "BABY-USDT",
#    "position_side": "LONG",
#    "sell_percentage": 2.5,
#    "price": 0.068186,
#    "leverage": 1,
#    "FIREBASE_SECRET": "",
#    "alarm": 1,
#    "pyramiding": 8,
#    "sicherheit": 96,
#    "vyn": "ja"   wird bei vyn ja angegeben, wird die andere Firebase-url genommen
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
    position_value = 0  # neu

    if response.get("code") == 0:
        for pos in positions:
            if pos.get("symbol") == symbol and pos.get("positionSide", "").upper() == position_side.upper():
                if logs is not None:
                    logs.append(f"Gefundene Position: {pos}")
                try:
                    position_size = float(pos.get("size", 0))
                    if position_size == 0:
                        position_size = float(pos.get("positionAmt", 0))

                    position_value_str = pos.get("positionValue", "0")
                    position_value = float(position_value_str)
                    
                    if logs is not None:
                        logs.append(f"Position size (Coin): {position_size}")
                        logs.append(f"Position value (USDT): {position_value}")
                except (ValueError, TypeError) as e:
                    position_size = 0
                    position_value = 0
                    if logs is not None:
                        logs.append(f"Fehler beim Parsen der Positionsdaten: {e}")
                break
    else:
        if logs is not None:
            logs.append(f"API Antwort Fehlercode: {response.get('code')}")

    return position_size, position_value, raw_positions



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
    
def sende_telegram_nachricht(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return "Telegram nicht konfiguriert"
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text
    }
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

def firebase_speichere_ordergroesse(asset, betrag, firebase_secret, firebase_url):
    url = f"{firebase_url}/ordergroesse/{asset}.json?auth={firebase_secret}"
    data = {"usdt_amount": betrag}
    response = requests.put(url, json=data)
    return f"Ordergröße für {asset} gespeichert: {betrag}, Status: {response.status_code}"

def firebase_lese_ordergroesse(asset, firebase_secret, firebase_url):
    url = f"{firebase_url}/ordergroesse/{asset}.json?auth={firebase_secret}"
    response = requests.get(url)
    
    if response.status_code != 200:
        return None

    try:
        data = response.json()
        if isinstance(data, dict) and "usdt_amount" in data:
            return float(data["usdt_amount"])
        elif isinstance(data, (int, float)):
            return float(data)  # Fallback, falls nur ein roher Wert gespeichert wurde
    except Exception as e:
        print(f"[Fehler] Firebase JSON Parsing: {e}")

    return None


def firebase_loesche_ordergroesse(asset, firebase_secret, firebase_url):
    url = f"{firebase_url}/ordergroesse/{asset}.json?auth={firebase_secret}"
    response = requests.delete(url)
    return f"Ordergröße für {asset} gelöscht, Status: {response.status_code}"

def firebase_speichere_kaufpreis(asset, price, firebase_secret, firebase_url):
    url = f"{firebase_url}/kaufpreise/{asset}.json?auth={firebase_secret}"
    data = {"price": price}
    response = requests.post(url, json=data)
    return f"Kaufpreis gespeichert für {asset}: {price}, Status: {response.status_code}"

def firebase_loesche_kaufpreise(asset, firebase_secret, firebase_url):
    url = f"{firebase_url}/kaufpreise/{asset}.json?auth={firebase_secret}"
    response = requests.delete(url)
    if response.status_code == 200:
        return f"Kaufpreise für {asset} gelöscht."
    else:
        return f"Fehler beim Löschen der Kaufpreise für {asset}: Status {response.status_code}"

def firebase_lese_kaufpreise(asset, firebase_secret, firebase_url):
    url = f"{firebase_url}/kaufpreise/{asset}.json?auth={firebase_secret}"
    response = requests.get(url)
    if response.status_code != 200:
        return None
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
    # Assuming you receive JSON data with a 'positionData' field
    data = request.json
    vyn = data.get("vyn", "nein").lower()
    if vyn == "ja":
        firebase_url = os.environ.get("FIREBASE_URL_vyn", "")
    else:
        firebase_url = os.environ.get("FIREBASE_URL", "")
        
    position_data = data.get('positionData', {})

    # Now use position_data safely
    position_value = float(position_data.get('positionValue', 0))

    logs = []

    api_key = data.get("api_key")
    secret_key = data.get("secret_key")
    symbol = data.get("symbol", "BTC-USDT")
    position_side = data.get("position_side") or data.get("positionSide") or "LONG"
    firebase_secret = data.get("FIREBASE_SECRET")

    

    if not api_key or not secret_key:
        return jsonify({"error": True, "msg": "api_key und secret_key sind erforderlich"}), 400

    base_asset = symbol.split("-")[0]

    # 1. Positionsgröße und Positionswert ermitteln
    sell_quantity = 0
    position_value = 0
    try:
        sell_quantity, position_value, _ = get_current_position(api_key, secret_key, symbol, position_side, logs)
    except Exception as e:
        logs.append(f"Fehler bei Positionsabfrage: {e}")

    position_in_usdt = round(position_value, 2)
    logs.append(f"Positionsgröße in USDT: {position_in_usdt}")

    # 2. Aktuellen Preis abfragen
    current_price = None
    try:
        current_price = get_current_price(symbol)
        logs.append(f"Aktueller Preis: {current_price}")
    except Exception as e:
        logs.append(f"Fehler beim Abrufen des aktuellen Preises: {e}")

    # 3. Kaufpreise aus Firebase lesen
    kaufpreise = []
    durchschnittspreis = None
    try:
        if firebase_secret:
            kaufpreise = firebase_lese_kaufpreise(base_asset, firebase_secret, firebase_url) or []
            durchschnittspreis = berechne_durchschnittspreis(kaufpreise)
            logs.append(f"Firebase Kaufpreise: {kaufpreise}")
            logs.append(f"Berechneter Durchschnittspreis: {durchschnittspreis}")
    except Exception as e:
        logs.append(f"Fehler beim Lesen/Berechnen der Kaufpreise: {e}")

    # 4. Positionsgröße in USDT berechnen (Menge * Durchschnittspreis)
    position_value = float(position_data.get('positionValue', 0))
    
    position_in_usdt = None
    position_in_usdt = round(position_value, 2)
    logs.append(f"Positionsgröße in USDT: {position_in_usdt}")

    # 5. Sell-Limit-Order Position (Preis) ermitteln
    limit_order_price = None
    try:
        open_orders = get_open_orders(api_key, secret_key, symbol)
        if isinstance(open_orders, dict) and open_orders.get("code") == 0:
            for order in open_orders.get("data", {}).get("orders", []):
                if order.get("side") == "SELL" and order.get("positionSide") == position_side and order.get("type") == "LIMIT":
                    limit_order_price = float(order.get("price"))
                    logs.append(f"Gefundene Sell-Limit-Order zum Preis: {limit_order_price}")
                    break
    except Exception as e:
        logs.append(f"Fehler beim Abrufen der offenen Sell-Limit-Orders: {e}")

    # 6. Gewinn/Verlust in Prozent berechnen
    profit_loss_percent = None
    if current_price and durchschnittspreis:
        try:
            profit_loss_percent = round((current_price - durchschnittspreis) / durchschnittspreis * 100, 4)
            logs.append(f"Gewinn/Verlust in Prozent: {profit_loss_percent}%")
        except Exception as e:
            logs.append(f"Fehler bei Gewinn/Verlust Berechnung: {e}")

    return jsonify({
        "error": False,
        "position_size_usdt": position_in_usdt,
        "sell_limit_order_price": limit_order_price,
        "profit_loss_percent": profit_loss_percent,
        "firebase_kaufpreise": kaufpreise,
        "firebase_durchschnittspreis": durchschnittspreis,
        "logs": logs
    })
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)

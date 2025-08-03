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

def firebase_lese_ordergroesse(asset, firebase_secret):
    url = f"{FIREBASE_URL}/ordergroesse/{asset}.json?auth={firebase_secret}"
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

def firebase_lese_kaufpreise(asset, firebase_secret):
    url = f"{FIREBASE_URL}/kaufpreise/{asset}.json?auth={firebase_secret}"
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

def send_signed_request(method, endpoint, api_key, secret_key, params):
    timestamp = int(time.time() * 1000)
    params["timestamp"] = timestamp
    sorted_query = '&'.join([f"{k}={params[k]}" for k in sorted(params)])
    signature = generate_signature(secret_key, sorted_query)
    headers = {"X-BX-APIKEY": api_key}
    url = f"{BASE_URL}{endpoint}?{sorted_query}&signature={signature}"
    if method == "GET":
        return requests.get(url, headers=headers).json()
    return {}

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    logs = []

    # 🔒 Minimale Pflichtfelder
    api_key = data.get("api_key")
    secret_key = data.get("secret_key")
    firebase_secret = data.get("FIREBASE_SECRET")

    if not api_key or not secret_key or not firebase_secret:
        return jsonify({"error": True, "msg": "api_key, secret_key und FIREBASE_SECRET sind erforderlich"}), 400

    # ⚙️ Fallback-Defaults
    data = request.get_json()
    symbol = data.get("symbol")  # Symbol aus JSON speichern
    position_side = "LONG"

base_asset = symbol.split("-")[0]

    base_asset = symbol.split("-")[0]
    aktueller_preis = get_current_price(symbol)
    logs.append(f"Aktueller Preis für {symbol}: {aktueller_preis}")

    # 📈 Position ermitteln
    sell_quantity, raw_positions = get_current_position(api_key, secret_key, symbol, position_side, logs)

    # 📊 Firebase: Kaufpreise & Ordergröße
    kaufpreise = firebase_lese_kaufpreise(base_asset, firebase_secret)
    durchschnittspreis = berechne_durchschnittspreis(kaufpreise)
    usdt_amount = firebase_lese_ordergroesse(base_asset, firebase_secret)

    # 📉 Balance ermitteln
    balance_data = get_futures_balance(api_key, secret_key)
    available_usdt = 0
    if balance_data.get("code") == 0:
        balances = balance_data.get("data", {}).get("balance", [])
        for b in balances:
            if b.get("asset") == "USDT":
                available_usdt = float(b.get("availableMargin", 0))
                break

    position_value_usdt = round(sell_quantity * aktueller_preis, 2) if aktueller_preis else 0

    return jsonify({
        "error": False,
        "symbol": symbol,
        "usdt_amount": usdt_amount,
        "sell_quantity": sell_quantity,
        "sell_percentage": sell_percentage,
        "firebase_average_price": durchschnittspreis,
        "firebase_all_prices": kaufpreise,
        "usdt_balance_before_order": available_usdt,
        "position_value_usdt": position_value_usdt,
        "logs": logs
    })

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)

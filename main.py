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
        print("❌ Price response error:", data)
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
        "price": round(limit_price, 2),
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


# --- Firebase Funktion ---
def firebase_speichere_kaufpreis(asset, price, firebase_secret):
    url = f"{FIREBASE_URL}/kaufpreise/{asset}.json?auth={firebase_secret}"
    data = {"price": price}
    response = requests.post(url, json=data)
    print(f"[Firebase] Kaufpreis gespeichert für {asset}: {price}")

def firebase_lese_kaufpreise(asset, firebase_secret):
    url = f"{FIREBASE_URL}/kaufpreise/{asset}.json?auth={firebase_secret}"
    response = requests.get(url)
    if response.status_code != 200:
        print(f"[Firebase] Fehler beim Abrufen der Kaufpreise: {response.text}")
        return []

    data = response.json()
    if not data:
        return []

    return [eintrag.get("price") for eintrag in data.values() if isinstance(eintrag, dict) and "price" in eintrag]

def berechne_durchschnittspreis(preise: list):
    preise = [float(p) for p in preise if isinstance(p, (int, float, str)) and str(p).replace('.', '', 1).isdigit()]
    if not preise:
        return None
    return round(sum(preise) / len(preise), 4)

    sell_percentage = data.get("sell_percentage")  # z. B. 5 für +5%
    order_response = None

    # 💡 Verhindert NameError
    order_response = None
    
    if durchschnittspreis and sell_percentage and firebase_secret:
        try:
            # Preisaufschlag berechnen
            limit_price = durchschnittspreis * (1 + float(sell_percentage) / 100)

            # Aktuellen Coin-Bestand abrufen
            symbol_base = symbol.split("-")[0]  # z.B. BTC aus BTC-USDT
            balances = balance_response.get("data", {}).get("balance", [])
            asset_balance = next((item for item in balances if item.get("asset") == symbol_base), None)

            if asset_balance and float(asset_balance.get("availableBalance", 0)) > 0:
                coin_amount = float(asset_balance["availableBalance"])
                order_response = place_limit_sell_order(
                    api_key, secret_key, symbol, coin_amount, limit_price
                )
            else:
                print(f"[Limit Order] Kein verfügbares Guthaben für {symbol_base}")
        except Exception as e:
            print(f"[Limit Order] Fehler beim Platzieren der Limit-Order: {e}")



# --- Webhook-Endpunkt ---
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json

    api_key = data.get("api_key")
    secret_key = data.get("secret_key")
    symbol = data.get("symbol", "BTC-USDT")
    usdt_amount = data.get("usdt_amount")
    position_side = data.get("position_side") or data.get("positionSide") or "LONG"
    firebase_secret = data.get("FIREBASE_SECRET")
    price_from_webhook = data.get("price")  # <-- Preis aus Webhook

    if not api_key or not secret_key or not usdt_amount:
        return jsonify({"error": True, "msg": "api_key, secret_key and usdt_amount are required"}), 400

    balance_response = get_futures_balance(api_key, secret_key)
    order_response = place_market_order(api_key, secret_key, symbol, float(usdt_amount), position_side)

    # 🔥 Preis aus Webhook speichern
    if firebase_secret and price_from_webhook is not None:
        try:
            price_to_store = float(price_from_webhook)
            base_asset = symbol.split("-")[0]  # z. B. BTC aus BTC-USDT
            firebase_speichere_kaufpreis(base_asset, price_to_store, firebase_secret)
        except Exception as e:
            print(f"[Firebase] Fehler beim Speichern des Webhook-Preises: {e}")

    durchschnittspreis = None
    if firebase_secret:
        try:
            base_asset = symbol.split("-")[0]
            kaufpreise = firebase_lese_kaufpreise(base_asset, firebase_secret)
            durchschnittspreis = berechne_durchschnittspreis(kaufpreise)
        except Exception as e:
            print(f"[Firebase] Fehler beim Berechnen des Durchschnittspreises: {e}")

    return jsonify({
        "error": False,
        "available_balances": balance_response.get("data", {}).get("balance", {}),
        "order_result": order_response,
        "limit_order_result": order_response,
        "order_params": {
            "symbol": symbol,
            "usdt_amount": usdt_amount,
            "position_side": position_side,
            "price_from_webhook": price_from_webhook,
            "sell_percentage": sell_percentage
        },
        "firebase_average_price": durchschnittspreis
    })



# --- Flask App Start --- 
if __name__ == "__main__": 
    app.run(debug=True, host="0.0.0.0", port=5000)

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
        "price": round(limit_price, 6),
        "timeInForce": "GTC",
        "positionSide": position_side,
        "timestamp": timestamp
    }

    # Erstelle Query-String für Signatur auf Grundlage JSON-Parametern
    # Sortiert und mit gleichen Dezimalstellen wie gesendet:
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

    data = request.json  # oder request.get_json()
    sell_percentage = data.get('sell_percentage')
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

    # 1. Kontostand abfragen (optional, z.B. für Debug)
    balance_response = get_futures_balance(api_key, secret_key)

    # 2. Market-Order platzieren (Kauf)
    order_response = place_market_order(api_key, secret_key, symbol, float(usdt_amount), position_side)

    # 3. Kaufpreis aus Webhook speichern, falls angegeben
    if firebase_secret and price_from_webhook is not None:
        try:
            price_to_store = float(price_from_webhook)
            base_asset = symbol.split("-")[0]
            firebase_speichere_kaufpreis(base_asset, price_to_store, firebase_secret)
        except Exception as e:
            print(f"[Firebase] Fehler beim Speichern des Webhook-Preises: {e}")

    # 4. Durchschnittspreis aus Firebase ermitteln
    durchschnittspreis = None
    if firebase_secret:
        try:
            base_asset = symbol.split("-")[0]
            kaufpreise = firebase_lese_kaufpreise(base_asset, firebase_secret)
            durchschnittspreis = berechne_durchschnittspreis(kaufpreise)
        except Exception as e:
            print(f"[Firebase] Fehler beim Berechnen des Durchschnittspreises: {e}")

    limit_order_response = None

    # 5. Limit-Sell-Order basierend auf executedQty aus Market-Order platzieren
    if durchschnittspreis is not None and sell_percentage is not None and firebase_secret:
        try:
            limit_price = durchschnittspreis * (1 + float(sell_percentage) / 100)

            # Menge aus der Market-Order Response verwenden (nicht aus Balance!)
            executed_qty = float(order_response.get("data", {}).get("order", {}).get("executedQty", 0))

            if executed_qty > 0:
                # Limit-Sell-Order zum Schließen der Long-Position
                limit_order_response = place_limit_sell_order(
                    api_key, secret_key, symbol, executed_qty, limit_price, position_side="LONG"
                )
            else:
                print("[Limit Order] Keine ausgeführte Menge aus Market-Order gefunden, Limit-Order nicht platziert.")
        except Exception as e:
            print(f"[Limit Order] Fehler beim Platzieren der Limit-Order: {e}")

    
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
        "firebase_all_prices": kaufpreise   # <---- Hier die komplette Liste hinzufügen
    })





# --- Flask App Start --- 
if __name__ == "__main__": 
    app.run(debug=True, host="0.0.0.0", port=5000)

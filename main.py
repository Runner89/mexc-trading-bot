from flask import Flask, request, jsonify
import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode
import os

app = Flask(__name__)

BASE_URL = "https://open-api.bingx.com"
FIREBASE_URL = os.getenv("FIREBASE_URL")  # Muss in Environment gesetzt sein


def generate_signature(params: dict, secret: str):
    query_string = urlencode(sorted(params.items()))
    signature = hmac.new(secret.encode(), query_string.encode(), hashlib.sha256).hexdigest()
    # Rückgabe von Signatur und Query-String zum Debuggen
    return signature, query_string


def get_open_sell_limit_orders(symbol, api_key, secret_key):
    path = "/openApi/spot/v1/trade/openOrders"
    url = BASE_URL + path
    timestamp = int(time.time() * 1000)
    params = {"symbol": symbol, "timestamp": timestamp}
    signature, query_string = generate_signature(params, secret_key)
    params["signature"] = signature
    headers = {"X-BX-APIKEY": api_key}
    response = requests.get(url, headers=headers, params=params)
    try:
        resp_json = response.json()
    except Exception:
        resp_json = {}
    debug_info = {
        "signature": signature,
        "query_string": query_string,
        "request_url": response.url,
        "request_headers": headers,
        "request_params": params,
        "response_text": response.text,
        "response_status_code": response.status_code
    }
    return resp_json, debug_info


def cancel_order(order_id, symbol, api_key, secret_key):
    path = "/openApi/spot/v1/trade/cancelOrder"
    url = BASE_URL + path
    timestamp = int(time.time() * 1000)
    params = {"orderId": order_id, "symbol": symbol, "timestamp": timestamp}
    signature, query_string = generate_signature(params, secret_key)
    params["signature"] = signature
    headers = {"X-BX-APIKEY": api_key}
    response = requests.post(url, headers=headers, data=params)
    try:
        resp_json = response.json()
    except Exception:
        resp_json = {}
    debug_info = {
        "signature": signature,
        "query_string": query_string,
        "request_url": url,
        "request_headers": headers,
        "request_params": params,
        "response_text": response.text,
        "response_status_code": response.status_code
    }
    return resp_json, debug_info


def place_sell_limit_order(symbol, quantity, price, api_key, secret_key):
    path = "/openApi/spot/v1/trade/order"
    url = BASE_URL + path
    timestamp = int(time.time() * 1000)
    params = {
        "symbol": symbol,
        "side": "SELL",
        "type": "LIMIT",
        "price": str(price),
        "quantity": str(quantity),
        "timestamp": timestamp,
        "timeInForce": "GTC"
    }
    signature, query_string = generate_signature(params, secret_key)
    params["signature"] = signature
    headers = {
        "X-BX-APIKEY": api_key,
        "Content-Type": "application/x-www-form-urlencoded"
    }
    response = requests.post(url, headers=headers, data=params)
    try:
        resp_json = response.json()
    except Exception:
        resp_json = {"error": "Antwort kein JSON", "content": response.text}
    debug_info = {
        "signature": signature,
        "query_string": query_string,
        "request_url": url,
        "request_headers": headers,
        "request_params": params,
        "response_text": response.text,
        "response_status_code": response.status_code
    }
    return resp_json, debug_info


def get_asset_balance(asset, api_key, secret_key):
    path = "/openApi/spot/v1/account/balance"
    url = BASE_URL + path
    timestamp = int(time.time() * 1000)
    params = {"timestamp": timestamp}
    signature, query_string = generate_signature(params, secret_key)
    params["signature"] = signature
    headers = {"X-BX-APIKEY": api_key}

    try:
        response = requests.get(url, headers=headers, params=params)
        resp_url = response.url
        resp_text = response.text
        raw_response = response.json()
    except Exception as e:
        return 0.0, [], {}, {
            "error": f"Fehler beim Request oder Parsen: {e}",
            "response_url": resp_url if 'resp_url' in locals() else None,
            "response_text": resp_text if 'resp_text' in locals() else None,
        }

    asset_list = []
    matched_amount = 0.0

    try:
        data = raw_response
        if "data" in data and "balances" in data["data"] and isinstance(data["data"]["balances"], list):
            for asset_info in data["data"]["balances"]:
                name = asset_info.get("asset")
                available = asset_info.get("free")
                asset_list.append({"asset": name, "available": available})
                if name == asset:
                    try:
                        matched_amount = float(available)
                    except:
                        matched_amount = 0.0
    except Exception as e:
        return 0.0, [], raw_response, {
            "error": f"Fehler beim Verarbeiten der Antwort: {e}",
            "response_url": resp_url,
            "response_text": resp_text,
        }

    debug_info = {
        "signature": signature,
        "query_string": query_string,
        "request_url": url,
        "request_headers": headers,
        "request_params": params,
        "response_url": resp_url,
        "response_text": resp_text,
        "response_status_code": response.status_code
    }

    return matched_amount, asset_list, raw_response, debug_info


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    if not data:
        return jsonify({"error": "Kein JSON erhalten"}), 400

    required_keys = ["symbol", "side", "usdt_amount", "BINGX_API_KEY", "BINGX_SECRET_KEY"]
    missing = [k for k in required_keys if k not in data]
    if missing:
        return jsonify({"error": f"Fehlende Felder: {missing}"}), 400

    symbol = data["symbol"]
    side = data["side"].upper()
    amount = str(data["usdt_amount"])
    api_key = data["BINGX_API_KEY"]
    secret_key = data["BINGX_SECRET_KEY"]
    price = data.get("price")  # optional für Firebase
    firebase_secret = data.get("firebase_secret")  # optional
    limit_sell_percent = data.get("limit_sell_percent")  # optional

    # Market Kauf-Order
    path = "/openApi/spot/v1/trade/order"
    url = BASE_URL + path
    timestamp = int(time.time() * 1000)

    params = {
        "quoteOrderQty": amount,
        "side": side,
        "symbol": symbol,
        "timestamp": timestamp,
        "type": "MARKET"
    }

    signature, query_string = generate_signature(params, secret_key)
    params["signature"] = signature

    headers = {
        "X-BX-APIKEY": api_key,
        "Content-Type": "application/x-www-form-urlencoded"
    }

    response = requests.post(url, headers=headers, data=params)

    try:
        resp_json = response.json()
    except Exception:
        resp_json = {"error": "Antwort kein JSON", "content": response.text}

    avg_price = None
    sell_limit_order = None

    if response.status_code == 200:
        firebase_response = None
        firebase_resp_json = None

        # Firebase Eintrag hinzufügen, wenn Preis & Secret da sind
        if firebase_secret and price is not None:
            firebase_path = f"{FIREBASE_URL}/kaufpreise/{symbol}.json?auth={firebase_secret}"
            firebase_data = {"price": price}
            firebase_response = requests.post(firebase_path, json=firebase_data)
            try:
                firebase_resp_json = firebase_response.json()
            except Exception:
                firebase_resp_json = {"error": "Firebase Antwort kein JSON", "content": firebase_response.text}

            # Alle Preise abrufen, Durchschnitt berechnen
            get_prices_path = f"{FIREBASE_URL}/kaufpreise/{symbol}.json?auth={firebase_secret}"
            get_response = requests.get(get_prices_path)
            try:
                all_prices_data = get_response.json()
            except Exception:
                all_prices_data = {}

            prices_list = []
            if isinstance(all_prices_data, dict):
                for val in all_prices_data.values():
                    if isinstance(val, dict) and "price" in val:
                        try:
                            prices_list.append(float(val["price"]))
                        except (ValueError, TypeError):
                            pass

            if prices_list:
                avg_price = sum(prices_list) / len(prices_list)

        # Sell-Limit-Preis berechnen
        if avg_price is not None and limit_sell_percent is not None:
            try:
                percent = float(limit_sell_percent)
                sell_limit_order = avg_price * (1 + percent / 100)
            except (ValueError, TypeError):
                sell_limit_order = None

        cancel_responses = []
        sell_limit_response = None
        sell_limit_debug_info = None

        if sell_limit_order is not None:
            # Coin aus Symbol extrahieren (funktioniert auch bei "ONDOUSDT", "ONDO-USDT", etc.)
            coin = symbol.replace("USDT", "").replace("-", "").replace("/", "")

            # Verfügbare Menge des Coins abfragen
            coin_amount, all_assets, asset_raw_response, asset_debug_info = get_asset_balance(coin, api_key, secret_key)

            if coin_amount > 0:
                sell_limit_response, sell_limit_debug_info = place_sell_limit_order(symbol, str(coin_amount), sell_limit_order, api_key, secret_key)
            else:
                sell_limit_response = {"error": f"Keine verfügbare Menge von {coin} zum Verkauf gefunden."}

        return jsonify({
            "order_status_code": response.status_code,
            "order_response": resp_json,
            "order_signature_debug": {
                "signature": signature,
                "query_string": query_string,
                "request_params": params,
                "request_url": url,
                "request_headers": headers,
                "response_text": response.text,
                "response_status_code": response.status_code,
            },
            "firebase_status_code": firebase_response.status_code if firebase_response else None,
            "firebase_response": firebase_resp_json,
            "average_price": avg_price,
            "sell_limit_order": sell_limit_order,
            "cancel_sell_limit_orders_response": cancel_responses,
            "sell_limit_order_response": sell_limit_response,
            "sell_limit_order_debug": sell_limit_debug_info,
            "available_assets": all_assets,
            "asset_api_raw_response": asset_raw_response,
            "asset_api_debug_info": asset_debug_info
        })

    else:
        return jsonify({
            "order_status_code": response.status_code,
            "order_response": resp_json,
            "message": "Order fehlgeschlagen, Firebase Update nicht ausgeführt.",
            "average_price": None,
            "sell_limit_order": None
        }), 400


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

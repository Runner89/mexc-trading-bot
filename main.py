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
    body = query_string + f"&signature={signature}"

    headers = {
        "X-BX-APIKEY": api_key,
        "Content-Type": "application/x-www-form-urlencoded"
    }
    response = requests.post(url, headers=headers, data=body)

    try:
        resp_json = response.json()
    except Exception:
        resp_json = {"error": "Antwort kein JSON", "content": response.text}

    debug_info = {
        "signature": signature,
        "query_string": query_string,
        "request_url": url,
        "request_headers": headers,
        "request_body": body,
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
        raw_response = response.json()
    except Exception as e:
        return 0.0, [], {}, {
            "error": f"Fehler beim Request oder Parsen: {e}",
            "response_text": response.text if 'response' in locals() else None,
        }

    matched_amount = 0.0
    asset_list = []

    try:
        balances = raw_response.get("data", {}).get("balances", [])
        for asset_info in balances:
            name = asset_info.get("asset")
            available = asset_info.get("free")
            asset_list.append({"asset": name, "available": available})
            if name == asset:
                try:
                    matched_amount = float(available)
                except:
                    matched_amount = 0.0
    except Exception as e:
        return 0.0, [], raw_response, {"error": str(e)}

    debug_info = {
        "signature": signature,
        "query_string": query_string,
        "request_url": url,
        "request_params": params,
        "response_text": response.text,
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

    # Parameter vorbereiten
    symbol = data["symbol"].replace("-", "").replace("/", "").upper()
    side = data["side"].upper()
    amount = str(data["usdt_amount"])
    api_key = data["BINGX_API_KEY"]
    secret_key = data["BINGX_SECRET_KEY"]
    price = data.get("price")
    firebase_secret = data.get("firebase_secret")
    limit_sell_percent = data.get("limit_sell_percent")

    # MARKTKAUF durchführen
    timestamp = int(time.time() * 1000)
    market_params = {
        "quoteOrderQty": amount,
        "side": side,
        "symbol": symbol,
        "timestamp": timestamp,
        "type": "MARKET"
    }
    signature, query_string = generate_signature(market_params, secret_key)
    market_params["signature"] = signature
    headers = {"X-BX-APIKEY": api_key, "Content-Type": "application/x-www-form-urlencoded"}
    response = requests.post(BASE_URL + "/openApi/spot/v1/trade/order", headers=headers, data=market_params)

    try:
        resp_json = response.json()
    except Exception:
        resp_json = {"error": "Antwort kein JSON", "content": response.text}

    avg_price = None
    sell_limit_order = None
    firebase_response = None
    firebase_resp_json = None
    cancel_responses = []
    sell_limit_response = {}
    sell_limit_debug_info = {}
    all_assets = []
    asset_raw_response = {}
    asset_debug_info = {}
    open_orders_debug = {}
    open_orders_data = []

    if response.status_code == 200 and firebase_secret and price is not None:
        firebase_path = f"{FIREBASE_URL}/kaufpreise/{symbol}.json?auth={firebase_secret}"
        firebase_data = {"price": price}
        firebase_response = requests.post(firebase_path, json=firebase_data)
        try:
            firebase_resp_json = firebase_response.json()
        except Exception:
            firebase_resp_json = {"error": "Firebase Antwort kein JSON", "content": firebase_response.text}

        get_prices_path = f"{FIREBASE_URL}/kaufpreise/{symbol}.json?auth={firebase_secret}"
        get_response = requests.get(get_prices_path)
        try:
            all_prices_data = get_response.json()
        except Exception:
            all_prices_data = {}

        prices_list = [float(val["price"]) for val in all_prices_data.values()
                       if isinstance(val, dict) and "price" in val and isinstance(val["price"], (int, float, str))]

        if prices_list:
            avg_price = sum(prices_list) / len(prices_list)

    if avg_price and limit_sell_percent:
        try:
            percent = float(limit_sell_percent)
            sell_limit_order = avg_price * (1 + percent / 100)
        except:
            sell_limit_order = None

    if sell_limit_order:
        coin = symbol.replace("USDT", "")
        open_orders_resp, open_orders_debug = get_open_sell_limit_orders(symbol, api_key, secret_key)
        open_orders_data = open_orders_resp.get("data", [])

        if isinstance(open_orders_data, list):
            for order in open_orders_data:
                if order.get("side") == "SELL" and order.get("type") == "LIMIT":
                    order_id = order.get("orderId")
                    cancel_resp, cancel_debug = cancel_order(order_id, symbol, api_key, secret_key)
                    cancel_responses.append({
                        "order_id": order_id,
                        "cancel_response": cancel_resp,
                        "cancel_debug": cancel_debug
                    })
        else:
            cancel_responses.append({"error": "Keine offenen Sell-Limit-Orders gefunden oder API Fehler."})

        # Verfügbare Menge abfragen & neue Sell-Limit-Order setzen
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
            "request_params": market_params,
            "request_url": BASE_URL + "/openApi/spot/v1/trade/order",
            "request_headers": headers,
            "response_text": response.text,
            "response_status_code": response.status_code
        },
        "firebase_status_code": firebase_response.status_code if firebase_response else None,
        "firebase_response": firebase_resp_json,
        "average_price": avg_price,
        "sell_limit_order_price": sell_limit_order,
        "cancel_sell_limit_orders_response": cancel_responses,
        "sell_limit_order_response": sell_limit_response,
        "sell_limit_order_debug": sell_limit_debug_info,
        "available_assets": all_assets,
        "asset_api_raw_response": asset_raw_response,
        "asset_api_debug_info": asset_debug_info,
        "open_orders_debug": open_orders_debug,
        "open_orders_data": open_orders_data
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

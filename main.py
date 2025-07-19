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
        resp_url = response.url
        resp_text = response.text
    except Exception as e:
        return 0.0, [], {}, {
            "error": f"Fehler beim Request oder Parsen: {e}",
            "response_url": None,
            "response_text": None,
        }
    asset_list = []
    matched_amount = 0.0
    if "data" in raw_response and "balances" in raw_response["data"]:
        for a in raw_response["data"]["balances"]:
            name = a.get("asset")
            free = a.get("free")
            asset_list.append({"asset": name, "available": free})
            if name == asset:
                try:
                    matched_amount = float(free)
                except:
                    matched_amount = 0.0
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

    required = ["symbol", "side", "usdt_amount", "BINGX_API_KEY", "BINGX_SECRET_KEY"]
    if any(k not in data for k in required):
        return jsonify({"error": "Fehlende Felder", "received": list(data.keys())}), 400

    symbol_raw = data["symbol"]
    symbol_normalized = symbol_raw.replace("-", "").replace("/", "").upper()
    side = data["side"].upper()
    amount = str(data["usdt_amount"])
    api_key = data["BINGX_API_KEY"]
    secret_key = data["BINGX_SECRET_KEY"]
    price = data.get("price")
    firebase_secret = data.get("firebase_secret")
    limit_sell_percent = data.get("limit_sell_percent")

    timestamp = int(time.time() * 1000)
    market_params = {
        "quoteOrderQty": amount,
        "side": side,
        "symbol": symbol_raw,
        "timestamp": timestamp,
        "type": "MARKET"
    }
    signature, query_string = generate_signature(market_params, secret_key)
    market_params["signature"] = signature
    headers = {
        "X-BX-APIKEY": api_key,
        "Content-Type": "application/x-www-form-urlencoded"
    }
    response = requests.post(BASE_URL + "/openApi/spot/v1/trade/order", headers=headers, data=market_params)
    try:
        resp_json = response.json()
    except Exception:
        resp_json = {"error": "Antwort kein JSON", "content": response.text}

    avg_price, sell_limit_order = None, None
    if response.status_code == 200 and firebase_secret and price is not None:
        firebase_data = {"price": price}
        post_url = f"{FIREBASE_URL}/kaufpreise/{symbol_normalized}.json?auth={firebase_secret}"
        firebase_response = requests.post(post_url, json=firebase_data)
        try:
            firebase_result = firebase_response.json()
        except:
            firebase_result = {"error": "Firebase Antwort kein JSON"}
        get_prices_url = f"{FIREBASE_URL}/kaufpreise/{symbol_normalized}.json?auth={firebase_secret}"
        get_response = requests.get(get_prices_url)
        try:
            all_prices = get_response.json()
        except:
            all_prices = {}
        price_list = [float(entry["price"]) for entry in all_prices.values() if "price" in entry]
        if price_list:
            avg_price = sum(price_list) / len(price_list)
    if avg_price and limit_sell_percent:
        try:
            percent = float(limit_sell_percent)
            sell_limit_order = avg_price * (1 + percent / 100)
        except:
            sell_limit_order = None

    cancel_responses, open_orders_debug = [], {}
    if sell_limit_order:
        open_orders_resp, open_orders_debug = get_open_sell_limit_orders(symbol_normalized, api_key, secret_key)
        orders = open_orders_resp.get("data", [])
        for o in orders:
            if o.get("side") == "SELL" and o.get("type") == "LIMIT":
                order_id = o.get("orderId")
                cancel_resp, cancel_debug = cancel_order(order_id, symbol_normalized, api_key, secret_key)
                cancel_responses.append({"order_id": order_id, "cancel_response": cancel_resp, "cancel_debug": cancel_debug})
        coin = symbol_normalized.replace("USDT", "")
        coin_amount, assets, asset_raw, asset_debug = get_asset_balance(coin, api_key, secret_key)
        if coin_amount > 0:
            sell_limit_response, sell_limit_debug = place_sell_limit_order(symbol_normalized, str(coin_amount), sell_limit_order, api_key, secret_key)
        else:
            sell_limit_response = {"error": f"Keine {coin} vorhanden"}
            sell_limit_debug = {}
    else:
        sell_limit_response = {}
        sell_limit_debug = {}
        assets, asset_raw, asset_debug = [], {}, {}

    return jsonify({
        "market_order_response": resp_json,
        "market_order_debug": {
            "signature": signature,
            "query_string": query_string,
            "params": market_params,
            "headers": headers,
            "status": response.status_code,
            "text": response.text
        },
        "firebase_response": firebase_result if firebase_secret else {},
        "average_price": avg_price,
        "sell_limit_price": sell_limit_order,
        "open_orders_debug": open_orders_debug,
        "cancelled_orders": cancel_responses,
        "sell_limit_order_response": sell_limit_response,
        "sell_limit_debug": sell_limit_debug,
        "available_assets": assets,
        "asset_balance_debug": asset_debug
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

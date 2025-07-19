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


def delete_all_firebase_prices(symbol, firebase_secret):
    if not FIREBASE_URL or not firebase_secret:
        return None
    firebase_path = f"{FIREBASE_URL}/kaufpreise/{symbol}.json?auth={firebase_secret}"
    response = requests.delete(firebase_path)
    try:
        return response.json()
    except Exception:
        return {"error": "Firebase delete Antwort kein JSON", "content": response.text}


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

    # 1. Market Kauf-Order ausführen
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

    cancel_responses = []
    sell_limit_response = None
    sell_limit_debug_info = None
    firebase_response = None
    firebase_resp_json = None
    all_assets = []
    asset_raw_response = {}
    asset_debug_info = {}

    if response.status_code == 200:
        # Vor dem Setzen der Sell-Limit-Order alle offenen Sell-Limit-Orders für das Symbol abrufen und löschen
        open_orders_resp, open_orders_debug = get_open_sell_limit_orders(symbol, api_key, secret_key)
        open_orders = open_orders_resp.get("data", []) if open_orders_resp else []

        for order in open_orders:
            if order.get("side") == "SELL" and order.get("type") == "LIMIT" and order.get("symbol") == symbol:
                cancel_resp, cancel_debug = cancel_order(order.get("orderId"), symbol, api_key, secret_key)
                cancel_responses.append({"orderId": order.get("orderId"), "cancel_response": cancel_resp})

        # Firebase: Prüfen ob noch offene Sell-Limit-Orders existieren
        # (Nach Löschung sind alle gelöscht, aber sicherheitshalber nochmal prüfen)
        open_orders_resp_after_cancel, _ = get_open_sell_limit_orders(symbol, api_key, secret_key)
        open_orders_after_cancel = open_orders_resp_after_cancel.get("data", []) if open_orders_resp_after_cancel else []

        sell_limit_exists = any(
            o.get("side") == "SELL" and o.get("type") == "LIMIT" and o.get("symbol") == symbol
            for o in open_orders_after_cancel
        )

        # Falls keine Sell-Limit-Orders existieren, Firebase löschen
        if not sell_limit_exists and firebase_secret:
            firebase_response = delete_all_firebase_prices(symbol, firebase_secret)

        # Nun Sell-Limit-Order setzen, falls angegeben
        if limit_sell_percent:
            try:
                limit_sell_percent = float(limit_sell_percent)
            except Exception:
                limit_sell_percent = None

        if limit_sell_percent is not None and float(amount) > 0:
            # Asset Balance abfragen, um Menge zu ermitteln
            # Dazu nehmen wir z.B. symbol="ONDOUSDT" -> Asset "ONDO"
            asset = symbol[:-4] if symbol.endswith("USDT") else symbol  # Annahme USDT als Quote
            asset_balance, all_assets, asset_raw_response, asset_debug_info = get_asset_balance(asset, api_key, secret_key)
            if asset_balance > 0:
                # Preis für Limit Sell berechnen
                avg_price = None
                if "avgPrice" in resp_json:
                    try:
                        avg_price = float(resp_json["avgPrice"])
                    except:
                        avg_price = None
                if not avg_price:
                    # Falls nicht im Kauf-Response vorhanden, benutze price aus Request falls vorhanden
                    avg_price = float(price) if price else None

                if avg_price:
                    sell_price = avg_price * (1 + limit_sell_percent / 100)
                    sell_limit_response, sell_limit_debug_info = place_sell_limit_order(symbol, asset_balance, sell_price, api_key, secret_key)

    return jsonify({
        "market_order_response": resp_json,
        "cancel_responses": cancel_responses,
        "sell_limit_order_response": sell_limit_response,
        "sell_limit_debug": sell_limit_debug_info,
        "firebase_delete_response": firebase_response,
        "asset_balance": asset_balance if 'asset_balance' in locals() else None,
        "all_assets": all_assets,
        "asset_raw_response": asset_raw_response,
        "asset_debug_info": asset_debug_info
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

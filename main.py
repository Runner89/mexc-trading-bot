import json
import time
import hmac
import hashlib
import requests

# Lade Konfiguration aus config.json
with open("config.json", "r") as f:
    config = json.load(f)

symbol = config["symbol"]
side = config["side"]
amount = config["usdt_amount"]
api_key = config["BINGX_API_KEY"]
secret_key = config["BINGX_SECRET_KEY"]

BASE_URL = "https://open-api.bingx.com"

def generate_signature(params: dict, secret: str) -> str:
    query_string = '&'.join(f"{key}={params[key]}" for key in sorted(params))
    return hmac.new(secret.encode(), query_string.encode(), hashlib.sha256).hexdigest()

def place_order():
    path = "/openApi/spot/v1/trade/order"
    url = BASE_URL + path
    timestamp = str(int(time.time() * 1000))

    params = {
        "symbol": symbol,
        "side": side,
        "type": "MARKET",
        "quoteOrderQty": amount,
        "timestamp": timestamp
    }

    signature = generate_signature(params, secret_key)
    params["signature"] = signature

    headers = {
        "X-BX-APIKEY": api_key
    }

    response = requests.post(url, headers=headers, data=params)
    print("Status:", response.status_code)
    print("Response:", response.json())

if __name__ == "__main__":
    place_order()

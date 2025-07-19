import os
import time
import hmac
import hashlib
import requests

# Konfiguration aus Umgebungsvariablen
symbol = os.getenv("SYMBOL", "NEXOUSDT")
side = os.getenv("SIDE", "BUY")
amount = os.getenv("USDT_AMOUNT", "1.5")
api_key = os.getenv("BINGX_API_KEY")
secret_key = os.getenv("BINGX_SECRET_KEY")

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

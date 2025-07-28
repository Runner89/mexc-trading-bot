import time
import hmac
import hashlib
import requests
import json

API_KEY = "DEIN_API_KEY"
API_SECRET = "DEIN_API_SECRET"

BASE_URL = "https://open-api.bingx.com"
ENDPOINT = "/openApi/swap/v2/user/balance"

def generate_signature(secret, params):
    return hmac.new(secret.encode(), params.encode(), hashlib.sha256).hexdigest()

def get_futures_balance():
    timestamp = int(time.time() * 1000)
    params = f"timestamp={timestamp}"
    signature = generate_signature(API_SECRET, params)
    url = f"{BASE_URL}{ENDPOINT}?{params}&signature={signature}"
    headers = {
        "X-BX-APIKEY": API_KEY
    }
    response = requests.get(url, headers=headers)
    data = response.json()
    return data

def main():
    balance_data = get_futures_balance()
    print(json.dumps(balance_data, indent=2))

if __name__ == "__main__":
    main()

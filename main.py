import time
import hmac
import hashlib
import requests

API_KEY = "AgKYtJTXgLDM7ZsiwaIUoJSUyrVXLjqkmFzLTfmCsau00nW1A6RQWddZQOOeAOzmcpDQ9zowa0BT8dG6BQ"
API_SECRET = "YyxO6LVeivvtYIzcIe9c8XWbedyzBWqIYgZdv8suYWWEAxVygafnsRYBqzImu0WMiZ4bxmxuih6Sf56Pn8bwQ"

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
    return response.json()

def main():
    data = get_futures_balance()
    print(data)

if __name__ == "__main__":
    main()

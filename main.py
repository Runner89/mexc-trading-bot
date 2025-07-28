import time
import hmac
import hashlib
import requests
import json

API_KEY = "AgKYtJTXgLDM7ZsiwaIUoJSUyrVXLjqkmFzLTfmCsau00nW1A6RQWddZQOOeAOzmcpDQ9zowa0BT8dG6BQ"
API_SECRET = "YyxO6LVeivvtYIzcIe9c8XWbedyzBWqIYgZdv8suYWWEAxVygafnsRYBqzImu0WMiZ4bxmxuih6Sf56Pn8bwQ"

BASE_URL = "https://open-api.bingx.com"
ENDPOINT = "/openApi/swap/v2/user/balance"

def generate_signature(secret, params):
    return hmac.new(secret.encode(), params.encode(), hashlib.sha256).hexdigest()

def get_futures_balance(api_key, api_secret):
    timestamp = int(time.time() * 1000)
    params = f"timestamp={timestamp}"
    signature = generate_signature(api_secret, params)
    url = f"{BASE_URL}{ENDPOINT}?{params}&signature={signature}"
    headers = {
        "X-BX-APIKEY": api_key
    }
    response = requests.get(url, headers=headers)
    
    if response.status_code != 200:
        return {
            "error": True,
            "status_code": response.status_code,
            "message": response.text
        }

    data = response.json()
    if data.get("code") != 0:
        return {
            "error": True,
            "message": data.get("msg", "API Fehler")
        }

    return {
        "error": False,
        "balances": data.get("data")
    }

def main():
    result = get_futures_balance(API_KEY, API_SECRET)
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
import time
import hmac
import hashlib
import requests
import json

# API Keys hier eintragen
API_KEY = "dein_api_key"
API_SECRET = "dein_api_secret"

BASE_URL = "https://open-api.bingx.com"
ENDPOINT = "/openApi/futures/v1/account/balance"

def generate_signature(secret, params):
    return hmac.new(secret.encode(), params.encode(), hashlib.sha256).hexdigest()

def get_futures_balance(api_key, api_secret):
    timestamp = int(time.time() * 1000)
    params = f"timestamp={timestamp}"
    signature = generate_signature(api_secret, params)
    url = f"{BASE_URL}{ENDPOINT}?{params}&signature={signature}"
    headers = {
        "X-BX-APIKEY": api_key
    }
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        return {
            "error": True,
            "status_code": response.status_code,
            "message": response.text
        }

    data = response.json()
    if data.get("code") != 0:
        return {
            "error": True,
            "message": data.get("msg", "API Fehler")
        }
    
    # Hier das relevante Kontostand-JSON zurückgeben
    return {
        "error": False,
        "balances": data["data"]["balances"]
    }

def main():
    result = get_futures_balance(API_KEY, API_SECRET)
    # Ausgabe als schön formatiertes JSON
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()

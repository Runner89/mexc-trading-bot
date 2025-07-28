from flask import Flask, request, jsonify
import hmac
import hashlib
import time
import requests

app = Flask(__name__)

# 🔐 Signatur erzeugen
def generate_signature(secret_key, query_string):
    return hmac.new(
        secret_key.encode(),
        query_string.encode(),
        hashlib.sha256
    ).hexdigest()

# 🕒 Zeitstempel erzeugen
def get_timestamp():
    return str(int(time.time() * 1000))

# 📡 Guthaben von BingX abrufen
def get_bingx_balance(api_key, secret_key):
    base_url = "https://open-api.bingx.com"
    endpoint = "/openApi/user/assets"  # Oder Spot: /openApi/spot/v1/account/balance
    timestamp = get_timestamp()
    query_string = f"timestamp={timestamp}"
    
    signature = generate_signature(secret_key, query_string)

    headers = {
        "X-BX-APIKEY": api_key,
        "Content-Type": "application/json",
        "signature": signature
    }

    params = {
        "timestamp": timestamp
    }

    try:
        response = requests.get(base_url + endpoint, headers=headers, params=params)
        return response.json()
    except Exception as e:
        return {"error": str(e)}

# 📥 Webhook-Route
@app.route("/webhook/balance", methods=["POST"])
def webhook_balance():
    data = request.get_json()

    # 🔍 Schlüssel prüfen
    if not data or "api_key" not in data or "secret_key" not in data:
        return jsonify({"error": "API Key und Secret Key sind erforderlich"}), 400

    api_key = data["api_key"]
    secret_key = data["secret_key"]

    result = get_bingx_balance(api_key, secret_key)

    # 🔄 Ergebnis zurückgeben
    return jsonify(result)

# ▶️ Server starten
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

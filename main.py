from flask import Flask, request, jsonify
from flask_cors import CORS
import hmac
import hashlib
import time
import requests
import os

app = Flask(__name__)
CORS(app)  # 🔓 CORS aktivieren (für Browser-Zugriffe)

# 🔐 HMAC-Signatur generieren
def generate_signature(secret_key, query_string):
    return hmac.new(
        secret_key.encode(),
        query_string.encode(),
        hashlib.sha256
    ).hexdigest()

# 🕒 Aktueller Timestamp in Millisekunden
def get_timestamp():
    return str(int(time.time() * 1000))

# 📡 API-Request an BingX senden
def get_bingx_balance(api_key, secret_key):
    url = "https://open-api.bingx.com/openApi/user/assets"
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
        response = requests.get(url, headers=headers, params=params)
        return response.json()
    except Exception as e:
        return {"error": str(e)}

# 🌐 POST-Endpunkt: /webhook/balance
@app.route("/webhook/balance", methods=["POST"])
def webhook_balance():
    data = request.get_json()
    if not data or "api_key" not in data or "secret_key" not in data:
        return jsonify({"error": "API Key und Secret Key sind erforderlich"}), 400

    result = get_bingx_balance(data["api_key"], data["secret_key"])
    return jsonify(result)

# ▶️ Starten (lokal oder auf Render.com)
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))  # Für Render.com und lokal
    app.run(host="0.0.0.0", port=port)

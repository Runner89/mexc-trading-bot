import os
from flask import Flask, request
import time, hmac, hashlib, requests
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    symbol = data.get("symbol")
    action = data.get("action") or data.get("side")
    usdt_amount = data.get("usdt_amount")
    quantity = data.get("quantity")

    if not all([symbol, action]):
        return "Missing symbol or action", 400

    # Wenn usdt_amount angegeben ist, berechne quantity anhand aktuellem Preis
    if usdt_amount is not None:
        price_url = f"https://api.mexc.com/api/v3/ticker/price?symbol={symbol}"
        try:
            price_response = requests.get(price_url)
            price_response.raise_for_status()
            price = float(price_response.json().get("price", 0))
            if price <= 0:
                return "Invalid price from MEXC", 500
            quantity = float(usdt_amount) / price
            # Optional: Runde quantity auf 4 Dezimalstellen (anpassen je nach Symbol)
            quantity = round(quantity, 4)
        except Exception as e:
            return f"Error getting price: {str(e)}", 500
    elif quantity is None:
        return "Missing quantity or usdt_amount", 400

    timestamp = int(time.time() * 1000)
    query = f"symbol={symbol}&side={action}&type=MARKET&quantity={quantity}&timestamp={timestamp}"
    secret = os.environ.get("MEXC_SECRET_KEY", "")
    api_key = os.environ.get("MEXC_API_KEY", "")
    signature = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    url = f"https://api.mexc.com/api/v3/order?{query}&signature={signature}"
    headers = {"X-MEXC-APIKEY": api_key}

    try:
        response = requests.post(url, headers=headers)
        return response.text, response.status_code
    except Exception as e:
        return str(e), 500

@app.route("/", methods=["GET"])
def home():
    return "✅ MEXC Python Bot läuft"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

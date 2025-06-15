import os
from flask import Flask, request, jsonify
import time, hmac, hashlib, requests

app = Flask(__name__)

def get_step_size(symbol):
    url = "https://api.mexc.com/api/v3/exchangeInfo"
    try:
        res = requests.get(url)
        data = res.json()
        for s in data.get("symbols", []):
            if s["symbol"] == symbol:
                for ftr in s.get("filters", []):
                    if ftr.get("filterType") == "LOT_SIZE":
                        return float(ftr.get("stepSize", 1))
        return None
    except Exception as e:
        return None

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    symbol = data.get("symbol")
    action = data.get("action")
    quantity = data.get("quantity")

    if not symbol:
        return jsonify({"error": "Kein Symbol angegeben"}), 400

    step_size = get_step_size(symbol)
    if step_size is None:
        return jsonify({"error": "Step size nicht gefunden oder ungültiges Symbol"}), 400

    # Zum Testen: einfach die Step Size zurückgeben
    return jsonify({"symbol": symbol, "step_size": step_size}), 200

@app.route("/", methods=["GET"])
def home():
    return "✅ MEXC Python Bot läuft"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

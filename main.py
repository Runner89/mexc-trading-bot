from flask import Flask, request, jsonify
import requests, time, hmac, hashlib, os

app = Flask(__name__)

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    symbol = data.get("symbol")  # z. B. BTCUSDT
    action = data.get("action")  # BUY oder SELL
    usdt_amount = data.get("usdt_amount")  # z. B. 15

    if not all([symbol, action, usdt_amount]):
        return jsonify({"error": "symbol, action oder usdt_amount fehlen"}), 400

    # 1. Hole exchangeInfo
    try:
        exchange_info = requests.get("https://api.mexc.com/api/v3/exchangeInfo").json()
    except Exception as e:
        return jsonify({"error": f"Fehler beim Abrufen der exchangeInfo: {str(e)}"}), 500

    symbol_info = next((s for s in exchange_info.get("symbols", []) if s["symbol"] == symbol), None)
    if not symbol_info:
        return jsonify({"error": "Symbol nicht gefunden"}), 400

    lot_size = next((f for f in symbol_info["filters"] if f["filterType"] == "LOT_SIZE"), None)
    if not lot_size:
        return jsonify({"error": "LOT_SIZE Filter nicht gefunden", "filters": symbol_info.get("filters", [])}), 400

    min_qty = float(lot_size["minQty"])
    step_size = float(lot_size["stepSize"])

    # 2. Hole aktuellen Preis
    try:
        price_info = requests.get(f"https://api.mexc.com/api/v3/ticker/price?symbol={symbol}").json()
        price = float(price_info["price"])
    except Exception as e:
        return jsonify({"error": f"Fehler beim Abrufen des Preises: {str(e)}"}), 500

    # 3. Berechne Menge
    quantity = float(usdt_amount) / price
    precision = len(str(step_size).split('.')[-1])
    quantity = round(quantity, precision)

    if quantity < min_qty:
        return jsonify({"error": "Berechnete Menge ist kleiner als minQty", "minQty": min_qty}), 400

    # 4. Sende Order
    api_key = os.getenv("MEXC_API_KEY")
    secret_key = os.getenv("MEXC_SECRET_KEY")

    if not api_key or not secret_key:
        return jsonify({"error": "API Key oder Secret nicht gesetzt"}), 500

    timestamp = int(time.time() * 1000)
    query_string = f"symbol={symbol}&side={action.upper()}&type=MARKET&quantity={quantity}&timestamp={timestamp}"
    signature = hmac.new(secret_key.encode(), query_string.encode(), hashlib.sha256).hexdigest()

    headers = {
        'X-MEXC-APIKEY': api_key
    }

    url = f"https://api.mexc.com/api/v3/order?{query_string}&signature={signature}"

    try:
        response = requests.post(url, headers=headers)
        return jsonify(response.json())
    except Exception as e:
        return jsonify({"error": f"Fehler beim Senden der Order: {str(e)}"}), 500

@app.route("/", methods=["GET"])
def index():
    return "✅ MEXC Spot-Trading Bot läuft"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

import os
from flask import Flask, request, jsonify
import time, hmac, hashlib, requests

app = Flask(__name__)

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    symbol = data.get("symbol")
    action = data.get("action")
    usdt_amount = data.get("usdt_amount")

    if not all([symbol, action, usdt_amount]):
        return jsonify({"error": "symbol, action und usdt_amount müssen gesetzt sein"}), 400

    # Hole Symbol-Infos von Mexc API
    try:
        res = requests.get("https://api.mexc.com/api/v3/exchangeInfo")
        res.raise_for_status()
        data_api = res.json()
    except Exception as e:
        return jsonify({"error": f"Fehler bei API-Anfrage: {str(e)}"}), 500

    # Symbol finden
    symbol_info = next((s for s in data_api.get("symbols", []) if s["symbol"] == symbol), None)
    if not symbol_info:
        return jsonify({"error": "Symbol nicht gefunden"}), 400

    # LOT_SIZE Filter holen
    lot_size_filter = next((f for f in symbol_info.get("filters", []) if f["filterType"] == "LOT_SIZE"), None)

    # Step Size definieren (Fallback falls nicht gefunden)
    if lot_size_filter:
        try:
            step_size = float(lot_size_filter.get("stepSize", "0"))
            if step_size == 0:
                step_size = 0.000001  # Fallback Step-Size
        except:
            step_size = 0.000001
    else:
        step_size = 0.000001  # Fallback wenn kein Filter da

    # Beispiel: Preis holen, um Menge zu berechnen (du kannst hier anpassen, wie du Menge berechnest)
    try:
        price_res = requests.get(f"https://api.mexc.com/api/v3/ticker/price?symbol={symbol}")
        price_res.raise_for_status()
        price = float(price_res.json().get("price", "0"))
    except Exception as e:
        return jsonify({"error": f"Fehler beim Preis holen: {str(e)}"}), 500

    if price == 0:
        return jsonify({"error": "Preis 0, Order nicht möglich"}), 400

    # Menge berechnen (usdt_amount / price)
    quantity_raw = usdt_amount / price

    # Menge an Step Size anpassen (abrunden auf nächstes Vielfaches)
    quantity = round(quantity_raw - (quantity_raw % step_size), 8)
    if quantity <= 0:
        return jsonify({"error": "Berechnete Menge <= 0, ungültig"}), 400

    # Signatur und Request vorbereiten
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
        return jsonify({"error": str(e)}), 500

@app.route("/", methods=["GET"])
def home():
    return "✅ MEXC Python Bot läuft"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

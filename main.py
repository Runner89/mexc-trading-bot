import os
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    symbol = data.get("symbol")

    if not symbol:
        return jsonify({"error": "Kein Symbol angegeben"}), 400

    url = "https://api.mexc.com/api/v3/exchangeInfo"
    try:
        res = requests.get(url)
        data_api = res.json()
    except Exception as e:
        return jsonify({"error": f"Fehler bei API-Anfrage: {str(e)}"}), 500

    symbol_info = next((s for s in data_api.get("symbols", []) if s["symbol"] == symbol), None)
    if not symbol_info:
        return jsonify({
            "error": "Symbol nicht gefunden",
            "gesuchte_symbol": symbol,
            "verfügbare_symbole_beispiel": [s["symbol"] for s in data_api.get("symbols", [])[:10]]
        }), 400

    filters = symbol_info.get("filters", [])

    lot_size_filter = next((f for f in filters if f.get("filterType") == "LOT_SIZE"), None)
    if not lot_size_filter:
        return jsonify({
            "error": "LOT_SIZE Filter nicht gefunden",
            "symbol": symbol,
            "filters": filters
        }), 400

    # Optional: hier kannst du weitere Logik einbauen, z.B. Menge validieren etc.

    return jsonify({
        "message": f"Symbol {symbol} gefunden mit LOT_SIZE Filter",
        "lot_size_filter": lot_size_filter
    }), 200

@app.route("/", methods=["GET"])
def home():
    return "✅ MEXC Trading Bot läuft"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

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
        return jsonify({"error": "Symbol nicht gefunden"}), 400

    lot_size_filter = next((f for f in symbol_info.get("filters", []) if f.get("filterType") == "LOT_SIZE"), None)
    if not lot_size_filter:
        return jsonify({"error": "LOT_SIZE Filter nicht gefunden"}), 400

    step_size = lot_size_filter.get("stepSize")

    return jsonify({
        "symbol": symbol,
        "stepSize": step_size,
        "filters": symbol_info.get("filters", [])
    }), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

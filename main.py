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
            "verfügbare_symbole_beispiel": [s["symbol"] for s in data_api.get("symbols", [])][:10]
        }), 400

    filters = symbol_info.get("filters", [])
    lot_size_filter = next((f for f in filters if f.get("filterType") == "LOT_SIZE"), None)

    if lot_size_filter:
        try:
            step_size = float(lot_size_filter["stepSize"])
        except (KeyError, ValueError):
            return jsonify({"error": "Ungültiger stepSize Wert im LOT_SIZE Filter"}), 400
    else:
        # Fallback: baseSizePrecision als step_size nutzen
        precision = symbol_info.get("baseSizePrecision")
        if precision is None:
            return jsonify({
                "error": "LOT_SIZE Filter nicht gefunden und baseSizePrecision fehlt",
                "filters": filters,
                "symbol": symbol
            }), 400
        try:
            precision_int = int(precision)
            step_size = 10 ** (-precision_int)
        except Exception:
            return jsonify({"error": "Ungültiger baseSizePrecision Wert"}), 400

    # Beispiel: Ausgabe step_size zur Kontrolle
    return jsonify({
        "symbol": symbol,
        "step_size": step_size,
        "filters": filters
    }), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

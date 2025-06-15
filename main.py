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

    # Alle Symbole ausgeben (zum Debuggen, kannst du später entfernen)
    symbol_list = [s["symbol"] for s in data_api.get("symbols", [])]

    # Versuche, das Symbol im API-Response zu finden
    symbol_info = next((s for s in data_api.get("symbols", []) if s["symbol"] == symbol), None)
    if not symbol_info:
        return jsonify({
            "error": "Symbol nicht gefunden",
            "gesuchte_symbol": symbol,
            "verfügbare_symbole_beispiel": symbol_list[:10]  # zeige 10 Symbole als Beispiel
        }), 400

    # Zeige Filters des Symbols zum Debuggen
    filters = symbol_info.get("filters", [])

    return jsonify({
        "symbol": symbol,
        "filters": filters
    }), 200

@app.route("/", methods=["GET"])
def home():
    return "✅ MEXC Python Bot läuft"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

def truncate_quantity(quantity, step_size):
    # Bestimme Nachkommastellen von step_size
    step_str = f"{step_size:.8f}".rstrip('0')
    if '.' in step_str:
        decimals = len(step_str.split('.')[1])
    else:
        decimals = 0

    # Auf erlaubte Nachkommastellen runden
    return float(f"{quantity:.{decimals}f}")

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    symbol = data.get("symbol")
    usdt_amount = data.get("usdt_amount")

    if not symbol:
        return jsonify({"error": "Kein Symbol angegeben"}), 400
    if not usdt_amount or usdt_amount <= 0:
        return jsonify({"error": "Ungültiger usdt_amount Wert"}), 400

    # Mexc API info holen
    url = "https://api.mexc.com/api/v3/exchangeInfo"
    try:
        res = requests.get(url)
        data_api = res.json()
    except Exception as e:
        return jsonify({"error": f"Fehler bei API-Anfrage: {str(e)}"}), 500

    # Symbolinfos suchen
    symbol_info = next((s for s in data_api.get("symbols", []) if s["symbol"] == symbol), None)
    if not symbol_info:
        return jsonify({
            "error": "Symbol nicht gefunden",
            "gesuchte_symbol": symbol,
            "verfügbare_symbole_beispiel": [s["symbol"] for s in data_api.get("symbols", [])[:10]]
        }), 400

    filters = symbol_info.get("filters", [])
    # LOT_SIZE Filter suchen
    lot_size_filter = next((f for f in filters if f.get("filterType") == "LOT_SIZE"), None)
    if not lot_size_filter:
        return jsonify({
            "error": "LOT_SIZE Filter nicht gefunden",
            "filters": filters,
            "symbol": symbol
        }), 400

    step_size = float(lot_size_filter["stepSize"])

    # Aktuellen Preis holen (für Beispiel hier: nimm letzter Preis aus Ticker)
    price_url = f"https://api.mexc.com/api/v3/ticker/price?symbol={symbol}"
    try:
        price_res = requests.get(price_url)
        price_data = price_res.json()
        price = float(price_data.get("price", 0))
        if price <= 0:
            return jsonify({"error": "Ungültiger Preis vom API"}), 400
    except Exception as e:
        return jsonify({"error": f"Fehler beim Preis holen: {str(e)}"}), 500

    # Menge berechnen: usdt_amount / price
    quantity_raw = usdt_amount / price

    # Menge an step_size anpassen
    quantity_rounded = quantity_raw - (quantity_raw % step_size)
    quantity = truncate_quantity(quantity_rounded, step_size)

    if quantity <= 0:
        return jsonify({"error": "Berechnete Menge <= 0, ungültig"}), 400

    # Zum Test: Gib Menge und Symbol zurück
    return jsonify({
        "symbol": symbol,
        "usdt_amount": usdt_amount,
        "price": price,
        "quantity_raw": quantity_raw,
        "quantity_rounded": quantity_rounded,
        "quantity_final": quantity
    }), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

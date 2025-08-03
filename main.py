from flask import Flask, request, jsonify

app = Flask(__name__)

def get_open_position_size(api_key, secret_key, symbol, position_side):
    # Beispiel für Binance Futures API Endpunkt "Position Information"
    url = "https://fapi.binance.com/fapi/v2/positionRisk"
    headers = {"X-MBX-APIKEY": api_key}
    params = {}

    response = requests.get(url, headers=headers, params=params)
    if response.status_code != 200:
        print("Fehler beim Abrufen der Positionen:", response.text)
        return 0

    positions = response.json()
    for pos in positions:
        if pos["symbol"] == symbol.replace("-", "") and pos["positionSide"] == position_side:
            size = float(pos["positionAmt"])
            return abs(size)  # Positionsgröße (ohne Vorzeichen)

    return 0  # Keine offene Position gefunden

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    symbol = data.get("symbol")  # z.B. "ALCH-USDT"
    api_key = data.get("api_key")
    secret_key = data.get("secret_key")

    if not symbol or not api_key or not secret_key:
        return jsonify({"error": True, "msg": "Symbol, api_key und secret_key erforderlich"}), 400

    position_side = "LONG"
    symbol_api = symbol.replace("-", "")  # z.B. ALCHUSDT

    positionsize = get_open_position_size(api_key, secret_key, symbol_api, position_side)

    return jsonify({
        "error": False,
        "symbol": symbol,
        "positionsize": positionsize
    })

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)

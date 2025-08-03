from flask import Flask, request, jsonify

app = Flask(__name__)

# 🔧 Dummy-Funktionen (zum Ersetzen mit echten Implementierungen)
def get_current_price(symbol): return 0.05
def get_current_position(api_key, secret_key, symbol, position_side, logs): return 100, []
def firebase_lese_kaufpreise(asset, secret): return [0.05, 0.06, 0.07]
def berechne_durchschnittspreis(preise): return round(sum(preise) / len(preise), 6) if preise else 0
def firebase_lese_ordergroesse(asset, secret): return 120
def get_futures_balance(api_key, secret_key):
    return {
        "code": 0,
        "data": {
            "balance": [
                {"asset": "USDT", "availableMargin": 134.56}
            ]
        }
    }

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    symbol = data.get("symbol")

    if not symbol:
        return jsonify({"error": "Symbol fehlt im Webhook"}), 400

    # 🔒 Minimale Pflichtfelder
    api_key = data.get("api_key")
    secret_key = data.get("secret_key")
    firebase_secret = data.get("FIREBASE_SECRET")

    if not api_key or not secret_key or not firebase_secret:
        return jsonify({"error": True, "msg": "api_key, secret_key und FIREBASE_SECRET sind erforderlich"}), 400

    position_side = "LONG"
    sell_percentage = 1.5  # Fix gesetzt wie gewünscht
    logs = []

    base_asset = symbol.split("-")[0]
    aktueller_preis = get_current_price(symbol)
    logs.append(f"Aktueller Preis für {symbol}: {aktueller_preis}")

    # 📈 Position ermitteln
    sell_quantity, raw_positions = get_current_position(api_key, secret_key, symbol, position_side, logs)

    # 📊 Firebase: Kaufpreise & Ordergröße
    kaufpreise = firebase_lese_kaufpreise(base_asset, firebase_secret)
    durchschnittspreis = berechne_durchschnittspreis(kaufpreise)
    usdt_amount = firebase_lese_ordergroesse(base_asset, firebase_secret)

    # 📉 Balance ermitteln
    balance_data = get_futures_balance(api_key, secret_key)
    available_usdt = 0
    if balance_data.get("code") == 0:
        balances = balance_data.get("data", {}).get("balance", [])
        for b in balances:
            if b.get("asset") == "USDT":
                available_usdt = float(b.get("availableMargin", 0))
                break

    position_value_usdt = round(sell_quantity * aktueller_preis, 2) if aktueller_preis else 0

    return jsonify({
        "error": False,
        "symbol": symbol,
        "usdt_amount": usdt_amount,
        "sell_quantity": sell_quantity,
        "sell_percentage": sell_percentage,
        "firebase_average_price": durchschnittspreis,
        "firebase_all_prices": kaufpreise,
        "usdt_balance_before_order": available_usdt,
        "position_value_usdt": position_value_usdt,
        "logs": logs
    })

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)

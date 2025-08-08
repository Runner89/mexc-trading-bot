#Market Order mit Hebel wird gesetzt
#Hebel muss in Bingx selber vorher eingestellt werden
#Preis, welcher im JSON übergeben wurde, wird in Firebase gespeichert
#Durschnittspreis wird von Firebase berechnet und entsprechend die Sell-Limit Order gesetzt
#Bei Alarm wird angegeben, ab welcher SO ein Alarm via Telegramm gesendet wird
#Verfügbares Guthaben wird ermittelt
#Ordergrösse = (Verfügbares Guthaben - Sicherheit)/Pyramiding
#StopLoss 2% über Liquidationspreis
#Falls Firebaseverbindung fehlschlägt, wird der Durchschnittspreis aus Bingx -0.02% für die Berechnung der Sell-Limit-Order verwendet.

###### Funktioniert nur, wenn alle Order die gleiche Grösse haben (Durchschnittspreis stimmt sonst nicht in Firebase) #####

#https://......../webhook
#{
#    "api_key": "",
#    "secret_key": "",
#    "symbol": "BABY-USDT",
#    "position_side": "LONG",
#    "sell_percentage": 2.5,
#    "price": 0.068186,
#    "leverage": 1,
#    "FIREBASE_SECRET": "",
#    "alarm": 1,
#    "pyramiding": 8,
#    "sicherheit": 96
#}

from flask import Flask, request, jsonify
import time
import hmac
import hashlib
import requests
import os

app = Flask(__name__)

BASE_URL = "https://open-api.bingx.com"
BALANCE_ENDPOINT = "/openApi/swap/v2/user/balance"
ORDER_ENDPOINT = "/openApi/swap/v2/trade/order"
PRICE_ENDPOINT = "/openApi/swap/v2/quote/price"
OPEN_ORDERS_ENDPOINT = "/openApi/swap/v2/trade/openOrders"
FIREBASE_URL = os.environ.get("FIREBASE_URL", "")

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

saved_usdt_amounts = {}  # globales Dict für alle Coins
status_fuer_alle = {} 

def generate_signature(secret_key: str, params: str) -> str:
    return hmac.new(secret_key.encode('utf-8'), params.encode('utf-8'), hashlib.sha256).hexdigest()

def get_futures_balance(api_key: str, secret_key: str):
    timestamp = int(time.time() * 1000)
    params = f"timestamp={timestamp}"
    signature = generate_signature(secret_key, params)
    url = f"{BASE_URL}{BALANCE_ENDPOINT}?{params}&signature={signature}"
    headers = {"X-BX-APIKEY": api_key}
    response = requests.get(url, headers=headers)
    return response.json()

def get_current_price(symbol: str):
    url = f"{BASE_URL}{PRICE_ENDPOINT}?symbol={symbol}"
    response = requests.get(url)
    data = response.json()
    if data.get("code") == 0 and "data" in data and "price" in data["data"]:
        return float(data["data"]["price"])
    else:
        return None

def place_market_order(api_key, secret_key, symbol, usdt_amount, position_side="LONG"):
    price = get_current_price(symbol)
    if price is None:
        return {"code": 99999, "msg": "Failed to get current price"}

    quantity = round(usdt_amount / price, 6)
    timestamp = int(time.time() * 1000)

    params_dict = {
        "symbol": symbol,
        "side": "BUY",
        "type": "MARKET",
        "quantity": quantity,
        "positionSide": position_side,
        "timestamp": timestamp
    }

    query_string = "&".join(f"{k}={params_dict[k]}" for k in sorted(params_dict))
    signature = generate_signature(secret_key, query_string)
    params_dict["signature"] = signature

    url = f"{BASE_URL}{ORDER_ENDPOINT}"
    headers = {
        "X-BX-APIKEY": api_key,
        "Content-Type": "application/json"
    }

    response = requests.post(url, headers=headers, json=params_dict)
    return response.json()

def place_stop_loss_order(api_key, secret_key, symbol, quantity, stop_price, position_side="LONG"):
    timestamp = int(time.time() * 1000)

    params_dict = {
        "symbol": symbol,
        "side": "SELL",
        "type": "STOP_MARKET",
        "stopPrice": round(stop_price, 6),
        "quantity": round(quantity, 6),
        "positionSide": position_side,
        "timestamp": timestamp,
        "timeInForce": "GTC"
    }

    query_string = "&".join(f"{k}={params_dict[k]}" for k in sorted(params_dict))
    signature = generate_signature(secret_key, query_string)
    params_dict["signature"] = signature

    url = f"{BASE_URL}{ORDER_ENDPOINT}"
    headers = {
        "X-BX-APIKEY": api_key,
        "Content-Type": "application/json"
    }

    response = requests.post(url, headers=headers, json=params_dict)
    return response.json()

def send_signed_request(http_method, endpoint, api_key, secret_key, params=None):
    if params is None:
        params = {}

    timestamp = int(time.time() * 1000)
    params['timestamp'] = timestamp

    query_string = "&".join(f"{k}={params[k]}" for k in sorted(params))
    signature = hmac.new(secret_key.encode(), query_string.encode(), hashlib.sha256).hexdigest()
    params['signature'] = signature

    url = f"{BASE_URL}{endpoint}"
    headers = {"X-BX-APIKEY": api_key}

    if http_method == "GET":
        response = requests.get(url, headers=headers, params=params)
    elif http_method == "POST":
        response = requests.post(url, headers=headers, json=params)
    elif http_method == "DELETE":
        response = requests.delete(url, headers=headers, params=params)
    else:
        raise ValueError("Unsupported HTTP method")

    return response.json()

def get_current_position(api_key, secret_key, symbol, position_side, logs=None):
    endpoint = "/openApi/swap/v2/user/positions"
    params = {"symbol": symbol}
    response = send_signed_request("GET", endpoint, api_key, secret_key, params)

    positions = response.get("data", [])
    raw_positions = positions if isinstance(positions, list) else []

    if logs is not None:
        logs.append(f"Positions Rohdaten: {raw_positions}")

    position_size = 0
    liquidation_price = None

    if response.get("code") == 0:
        for pos in positions:
            if pos.get("symbol") == symbol and pos.get("positionSide", "").upper() == position_side.upper():
                if logs is not None:
                    logs.append(f"Gefundene Position: {pos}")
                try:
                    position_size = float(pos.get("size", 0)) or float(pos.get("positionAmt", 0))
                    liquidation_price = float(pos.get("liquidationPrice", 0))
                    if logs is not None:
                        logs.append(f"Position size: {position_size}, Liquidation price: {liquidation_price}")
                except (ValueError, TypeError) as e:
                    position_size = 0
                    if logs is not None:
                        logs.append(f"Fehler beim Parsen: {e}")
                break
    else:
        if logs is not None:
            logs.append(f"API Antwort Fehlercode: {response.get('code')}")

    return position_size, raw_positions, liquidation_price

def place_limit_sell_order(api_key, secret_key, symbol, quantity, limit_price, position_side="LONG"):
    timestamp = int(time.time() * 1000)

    params_dict = {
        "symbol": symbol,
        "side": "SELL",
        "type": "LIMIT",
        "quantity": round(quantity, 6),
        "price": round(limit_price, 6),
        "timeInForce": "GTC",
        "positionSide": position_side,
        "timestamp": timestamp
    }

    query_string = "&".join(f"{k}={params_dict[k]}" for k in sorted(params_dict))
    signature = generate_signature(secret_key, query_string)
    params_dict["signature"] = signature

    url = f"{BASE_URL}{ORDER_ENDPOINT}"
    headers = {
        "X-BX-APIKEY": api_key,
        "Content-Type": "application/json"
    }

    response = requests.post(url, headers=headers, json=params_dict)
    return response.json()
    
def sende_telegram_nachricht(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return "Telegram nicht konfiguriert"
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text
    }
    response = requests.post(url, json=payload)
    return f"Telegram Antwort: {response.status_code}"

    query_string = "&".join(f"{k}={params_dict[k]}" for k in sorted(params_dict))
    signature = generate_signature(secret_key, query_string)
    params_dict["signature"] = signature

    url = f"{BASE_URL}{ORDER_ENDPOINT}"
    headers = {
        "X-BX-APIKEY": api_key,
        "Content-Type": "application/json"
    }

    response = requests.post(url, headers=headers, json=params_dict)
    return response.json()

def get_open_orders(api_key, secret_key, symbol):
    timestamp = int(time.time() * 1000)
    params = f"symbol={symbol}&timestamp={timestamp}"
    signature = generate_signature(secret_key, params)
    url = f"{BASE_URL}{OPEN_ORDERS_ENDPOINT}?{params}&signature={signature}"
    headers = {"X-BX-APIKEY": api_key}
    response = requests.get(url, headers=headers)

    try:
        data = response.json()
    except ValueError:
        return {"code": -1, "msg": "Ungültige API-Antwort", "raw_response": response.text}

    return data

def cancel_order(api_key, secret_key, symbol, order_id):
    timestamp = int(time.time() * 1000)
    params = f"symbol={symbol}&orderId={order_id}&timestamp={timestamp}"
    signature = generate_signature(secret_key, params)
    url = f"{BASE_URL}{ORDER_ENDPOINT}?{params}&signature={signature}"
    headers = {"X-BX-APIKEY": api_key}
    response = requests.delete(url, headers=headers)
    return response.json()

def firebase_speichere_ordergroesse(asset, betrag, firebase_secret):
    url = f"{FIREBASE_URL}/ordergroesse/{asset}.json?auth={firebase_secret}"
    data = {"usdt_amount": betrag}
    response = requests.put(url, json=data)
    return f"Ordergröße für {asset} gespeichert: {betrag}, Status: {response.status_code}"

def firebase_lese_ordergroesse(asset, firebase_secret):
    url = f"{FIREBASE_URL}/ordergroesse/{asset}.json?auth={firebase_secret}"
    response = requests.get(url)
    
    if response.status_code != 200:
        return None

    try:
        data = response.json()
        if isinstance(data, dict) and "usdt_amount" in data:
            return float(data["usdt_amount"])
        elif isinstance(data, (int, float)):
            return float(data)  # Fallback, falls nur ein roher Wert gespeichert wurde
    except Exception as e:
        print(f"[Fehler] Firebase JSON Parsing: {e}")

    return None


def firebase_loesche_ordergroesse(asset, firebase_secret):
    url = f"{FIREBASE_URL}/ordergroesse/{asset}.json?auth={firebase_secret}"
    response = requests.delete(url)
    return f"Ordergröße für {asset} gelöscht, Status: {response.status_code}"

def firebase_speichere_kaufpreis(asset, price, firebase_secret):
    url = f"{FIREBASE_URL}/kaufpreise/{asset}.json?auth={firebase_secret}"
    data = {"price": price}
    response = requests.post(url, json=data)
    return f"Kaufpreis gespeichert für {asset}: {price}, Status: {response.status_code}"

def firebase_loesche_kaufpreise(asset, firebase_secret):
    url = f"{FIREBASE_URL}/kaufpreise/{asset}.json?auth={firebase_secret}"
    response = requests.delete(url)
    if response.status_code == 200:
        return f"Kaufpreise für {asset} gelöscht."
    else:
        return f"Fehler beim Löschen der Kaufpreise für {asset}: Status {response.status_code}"

def firebase_lese_kaufpreise(asset, firebase_secret):
    url = f"{FIREBASE_URL}/kaufpreise/{asset}.json?auth={firebase_secret}"
    response = requests.get(url)
    if response.status_code != 200:
        return None
    data = response.json()
    if not data:
        return []
    return [eintrag.get("price") for eintrag in data.values() if isinstance(eintrag, dict) and "price" in eintrag]

def berechne_durchschnittspreis(preise):
    preise = [float(p) for p in preise if isinstance(p, (int, float, str)) and str(p).replace('.', '', 1).isdigit()]
    return round(sum(preise) / len(preise), 6) if preise else None

def set_leverage(api_key, secret_key, symbol, leverage, position_side="LONG"):
    endpoint = "/openApi/swap/v2/trade/leverage"
    
    # mappe positionSide auf side für Hebel-Setzung
    side_map = {
        "LONG": "BUY",
        "SHORT": "SELL"
    }
    
    params = {
        "symbol": symbol,
        "leverage": int(leverage),
        "positionSide": position_side.upper(),
        "side": side_map.get(position_side.upper())  # korrektes Side-Value setzen
    }
    return send_signed_request("POST", endpoint, api_key, secret_key, params)

@app.route('/webhook', methods=['POST'])
def webhook():
    global saved_usdt_amounts
    global status_fuer_alle
    
    data = request.json
    logs = []
    base_asset = data.get("symbol", "BTC-USDT").split("-")[0]

     # Hole den gespeicherten Wert für den Coin, falls vorhanden
    saved_usdt_amount = saved_usdt_amounts.get(base_asset)

    # Eingabewerte
    pyramiding = float(data.get("pyramiding", 1))
    sicherheit = float(data.get("sicherheit", 0))
    sell_percentage = data.get("sell_percentage")
    api_key = data.get("api_key")
    secret_key = data.get("secret_key")
    symbol = data.get("symbol", "BTC-USDT")
    position_side = data.get("position_side") or data.get("positionSide") or "LONG"
    firebase_secret = data.get("FIREBASE_SECRET")
    price_from_webhook = data.get("price")

    

    if not api_key or not secret_key:
        return jsonify({"error": True, "msg": "api_key und secret_key sind erforderlich"}), 400

    base_asset = symbol.split("-")[0]
    available_usdt = 0.0

    # 0. USDT-Guthaben vor Order abrufen
    try:
        balance_response = get_futures_balance(api_key, secret_key)
        logs.append(f"Balance Response: {balance_response}")
        if balance_response.get("code") == 0:
            balance_data = balance_response.get("data", {}).get("balance", {})
            available_usdt = float(balance_data.get("availableMargin", 0))
            logs.append(f"Freies USDT Guthaben: {available_usdt}")
        else:
            logs.append("Fehler beim Abrufen der Balance.")
    except Exception as e:
        logs.append(f"Fehler bei Balance-Abfrage: {e}")
        available_usdt = None

    # 1. Hebel setzen
    try:
        logs.append(f"Setze Hebel auf {pyramiding} für {symbol} ({position_side})...")
        leverage_response = set_leverage(api_key, secret_key, symbol, pyramiding, position_side)
        logs.append(f"Hebel gesetzt: {leverage_response}")
    except Exception as e:
        logs.append(f"Fehler beim Setzen des Hebels: {e}")

    # 2. Offene Orders abrufen
    open_orders = {}
    try:
        open_orders = get_open_orders(api_key, secret_key, symbol)
        logs.append(f"Open Orders: {open_orders}")
    except Exception as e:
        logs.append(f"Fehler bei Orderprüfung: {e}")
        sende_telegram_nachricht(f"Fehler bei Orderprüfung {base_asset}: {e}")

# 3. Ordergröße ermitteln (Compounding-Logik)
    usdt_amount = 0

    if firebase_secret:
        try:
            open_sell_orders_exist = False
            if isinstance(open_orders, dict) and open_orders.get("code") == 0:
                for order in open_orders.get("data", {}).get("orders", []):
                    if order.get("side") == "SELL" and order.get("positionSide") == position_side and order.get("type") == "LIMIT":
                        open_sell_orders_exist = True
                        break
    
            # Falls keine offene Sell-Limit-Order existiert, neu berechnen und speichern
            if not open_sell_orders_exist:
                logs.append(firebase_loesche_ordergroesse(base_asset, firebase_secret))
                # Lokale Ordergröße ebenfalls aus dem Cache entfernen
                if base_asset in saved_usdt_amounts:
                    del saved_usdt_amounts[base_asset]
                    logs.append(f"Ordergröße aus Cache für {base_asset} gelöscht (keine offene Sell-Limit-Order)")
                if available_usdt is not None and pyramiding > 0:
                    usdt_amount = max((available_usdt - sicherheit) / pyramiding, 0)
                    saved_usdt_amounts[base_asset] = usdt_amount  # Dict aktualisieren
                    logs.append(f"Neue Ordergröße berechnet: {usdt_amount}")
                    logs.append(firebase_speichere_ordergroesse(base_asset, usdt_amount, firebase_secret))
    
            # Sonst gespeicherte Ordergröße holen
            saved_usdt_amount = saved_usdt_amounts.get(base_asset, 0)
    
            # Wenn saved_usdt_amount leer oder 0, dann aus Firebase lesen
            if not saved_usdt_amount or saved_usdt_amount == 0:
                usdt_amount = firebase_lese_ordergroesse(base_asset, firebase_secret) or 0
                if usdt_amount > 0:
                    saved_usdt_amounts[base_asset] = usdt_amount
                    logs.append(f"Ordergröße aus Firebase für {base_asset} gelesen: {usdt_amount}")
                else:
                    logs.append(f"⚠️ Keine Ordergröße in Variable oder Firebase für {base_asset} gefunden.")
                    sende_telegram_nachricht(f"keine Ordergrösse gefunden bei Coin: {base_asset}")
            else:
                usdt_amount = saved_usdt_amount
                logs.append(f"Verwende gespeicherte Ordergröße aus Dict für {base_asset}: {usdt_amount}")
    
        except Exception as e:
            logs.append(f"Fehler bei Ordergrößenberechnung: {e}")
            sende_telegram_nachricht(f"❌ Ausnahmefehler bei Ordergrößenberechnung für {base_asset}: {e}")

    # 4. Market-Order ausführen
    logs.append(f"Plaziere Market-Order mit {usdt_amount} USDT für {symbol} ({position_side})...")
    order_response = place_market_order(api_key, secret_key, symbol, float(usdt_amount), position_side)
    time.sleep(2)
    logs.append(f"Market-Order Antwort: {order_response}")

    # 5. Positionsgröße und Liquidationspreis ermitteln
    try:
        sell_quantity, positions_raw, liquidation_price = get_current_position(api_key, secret_key, symbol, position_side, logs)
    
        if sell_quantity == 0:
            executed_qty_str = order_response.get("data", {}).get("order", {}).get("executedQty")
            if executed_qty_str:
                sell_quantity = float(executed_qty_str)
                logs.append(f"[Market Order] Ausgeführte Menge aus order_response genutzt: {sell_quantity}")
    
        if liquidation_price:
            stop_loss_price = round(liquidation_price * 1.02, 6)
            logs.append(f"Stop-Loss-Preis basierend auf Liquidationspreis {liquidation_price}: {stop_loss_price}")
        else:
            stop_loss_price = None
            logs.append("Liquidationspreis nicht verfügbar. Kein Stop-Loss-Berechnung möglich.")
    except Exception as e:
        sell_quantity = 0
        stop_loss_price = None
        logs.append(f"Fehler bei Positions- oder Liquidationspreis-Abfrage: {e}")
        sende_telegram_nachricht(f"Fehler bei Positions- oder Liquidationspreis-Abfrage {base_asset}: {e}")

    # 6. Kaufpreise ggf. löschen
    if firebase_secret and not open_sell_orders_exist:
        try:
            logs.append(firebase_loesche_kaufpreise(base_asset, firebase_secret))
            status_fuer_alle.pop(symbol, None)
            status_fuer_alle[base_asset] = "OK"
        except Exception as e:
            logs.append(f"Fehler beim Löschen der Kaufpreise: {e}")
            status_fuer_alle[base_asset] = "Fehler"
            sende_telegram_nachricht(f"Fehler beim Löschen der Kaufpreise {base_asset}: {e}")

   # 7. Kaufpreis speichern + Status ggf. auf OK setzen
    if firebase_secret and price_from_webhook:
        try:
            result = firebase_speichere_kaufpreis(base_asset, float(price_from_webhook), firebase_secret)
            logs.append(result)

            # Falls Status nicht "Fehler" ist, auf OK setzen
            try:
                aktueller_status = status_fuer_alle.get(base_asset)
                if aktueller_status != "Fehler":
                    
                    firebase_speichere_status(base_asset, "OK", firebase_secret)
                    logs.append(f"Status für {base_asset} auf OK gesetzt.")
            except Exception as e:
                logs.append(f"Fehler beim Setzen des Status auf OK: {e}")

        except Exception as e:
            logs.append(f"Fehler beim Speichern des Kaufpreises: {e}")
            status_fuer_alle[base_asset] = "Fehler"
            sende_telegram_nachricht(f"Fehler beim Speichern des Kaufpreises {base_asset}: {e}")

  # 8. Durchschnittspreis bestimmen – abhängig vom Status
    durchschnittspreis = None
    kaufpreise = []
    
    try:
        aktueller_status = status_fuer_alle.get(base_asset)
    
        if aktueller_status == "Fehler":
            # Direkter BingX-Fallback
            logs.append(f"Status für {base_asset} ist 'Fehler' → direkt BingX-Fallback verwenden.")
            try:
                for pos in positions_raw:
                    if pos.get("symbol") == symbol and pos.get("positionSide", "").upper() == position_side.upper():
                        avg_price = float(pos.get("avgPrice", 0)) or float(pos.get("averagePrice", 0))
                        if avg_price > 0:
                            durchschnittspreis = round(avg_price * (1 - 0.002), 6)
                            logs.append(f"[Direkter Fallback] avgPrice aus Position verwendet: {durchschnittspreis}")
                        else:
                            logs.append("[Direkter Fallback] Kein gültiger avgPrice in Position vorhanden.")
                        break
            except Exception as e:
                logs.append(f"[Direkter Fallback Fehler] avgPrice konnte nicht berechnet werden: {e}")
                status_fuer_alle[base_asset] = "Fehler"
        else:
            # 1. Versuch: Firebase-Durchschnitt
            if firebase_secret:
                kaufpreise = firebase_lese_kaufpreise(base_asset, firebase_secret)
                durchschnittspreis = berechne_durchschnittspreis(kaufpreise or [])
                if durchschnittspreis:
                    logs.append(f"[Firebase] Durchschnittspreis berechnet: {durchschnittspreis}")
                else:
                    logs.append("[Firebase] Keine gültigen Kaufpreise gefunden.")
                    status_fuer_alle[base_asset] = "Fehler"
    
            # 2. Fallback BingX, wenn Firebase nichts liefert
            if not durchschnittspreis or durchschnittspreis == 0:
                try:
                    for pos in positions_raw:
                        if pos.get("symbol") == symbol and pos.get("positionSide", "").upper() == position_side.upper():
                            avg_price = float(pos.get("avgPrice", 0)) or float(pos.get("averagePrice", 0))
                            if avg_price > 0:
                                durchschnittspreis = round(avg_price * (1 - 0.002), 6)
                                logs.append(f"[Fallback] avgPrice aus Position verwendet: {durchschnittspreis}")
                            else:
                                logs.append("[Fallback] Kein gültiger avgPrice in Position vorhanden.")
                            break
                except Exception as e:
                    logs.append(f"[Fehler] avgPrice-Fallback fehlgeschlagen: {e}")
                    status_fuer_alle[base_asset] = "Fehler"
    
    except Exception as e:
        logs.append(f"[Fehler] Durchschnittspreis-Berechnung fehlgeschlagen: {e}")

    # 9. Alte Sell-Limit-Orders löschen
    try:
        if isinstance(open_orders, dict) and open_orders.get("code") == 0:
            for order in open_orders.get("data", {}).get("orders", []):
                if order.get("side") == "SELL" and order.get("positionSide") == position_side and order.get("type") == "LIMIT":
                    cancel_response = cancel_order(api_key, secret_key, symbol, str(order.get("orderId")))
                    logs.append(f"Gelöschte Order {order.get('orderId')}: {cancel_response}")
    except Exception as e:
        logs.append(f"Fehler beim Löschen der Sell-Limit-Orders: {e}")
        sende_telegram_nachricht(f"Fehler beim Löschen der Sell-Limit-Order {base_asset}: {e}")

    # 10. Neue Limit-Order setzen
    limit_order_response = None
    try:
        if durchschnittspreis and sell_percentage:
            limit_price = round(durchschnittspreis * (1 + float(sell_percentage) / 100), 6)
        else:
            limit_price = 0

        if sell_quantity > 0 and limit_price > 0:
            limit_order_response = place_limit_sell_order(api_key, secret_key, symbol, sell_quantity, limit_price, position_side)
            logs.append(f"Limit-Order gesetzt (auf Basis Durchschnittspreis {durchschnittspreis}): {limit_order_response}")
        else:
            logs.append("Ungültige Daten, keine Limit-Order gesetzt.")
    except Exception as e:
        logs.append(f"Fehler bei Limit-Order: {e}")
        sende_telegram_nachricht(f"Fehler bei Limit-Order {base_asset}: {e}")

    # 11. Bestehende STOP_MARKET SL-Orders löschen
    try:
        for order in open_orders.get("data", {}).get("orders", []):
            if order.get("type") == "STOP_MARKET" and order.get("positionSide") == position_side:
                cancel_response = cancel_order(api_key, secret_key, symbol, str(order.get("orderId")))
                logs.append(f"Bestehende SL-Order gelöscht: {cancel_response}")
    except Exception as e:
        logs.append(f"Fehler beim Löschen alter Stop-Market-Orders: {e}")
        sende_telegram_nachricht(f"Fehler beim alter Stop-Market Order {base_asset}: {e}")

    # 12. Stop-Loss Order setzen
    stop_loss_response = None
    try:
        if sell_quantity > 0 and stop_loss_price:
            stop_loss_response = place_stop_loss_order(api_key, secret_key, symbol, sell_quantity, stop_loss_price, position_side)
            logs.append(f"Stop-Loss Order gesetzt bei {stop_loss_price}: {stop_loss_response}")
        else:
            logs.append("Keine Stop-Loss Order gesetzt – unvollständige Daten.")
    except Exception as e:
        logs.append(f"Fehler beim Setzen der Stop-Loss Order: {e}")
        sende_telegram_nachricht(f"Fehler beim Setzen der Stop-Loss Order {base_asset}: {e}")

    # 11. Alarm senden
    alarm_trigger = int(data.get("alarm", 0))
    anzahl_käufe = len(kaufpreise or [])
    anzahl_nachkäufe = max(anzahl_käufe - 1, 0)

    if anzahl_nachkäufe >= alarm_trigger:
        try:
            nachricht = f"{base_asset}:\nNachkäufe: {anzahl_nachkäufe}"
            telegram_result = sende_telegram_nachricht(nachricht)
            logs.append(f"Telegram gesendet: {telegram_result}")

            if firebase_secret:
                firebase_speichere_alarmwert(base_asset, anzahl_käufe, firebase_secret)
                logs.append(f"Neuer Alarmwert in Firebase gespeichert: {anzahl_käufe}")
        except Exception as e:
            logs.append(f"Fehler beim Senden der Telegram-Nachricht: {e}")
            sende_telegram_nachricht(f"Fehler beim Senden der Telegram-Nachricht {base_asset}: {e}")

    

    return jsonify({
        "error": False,
        "order_result": order_response,
        "limit_order_result": limit_order_response,
        "symbol": symbol,
        "usdt_amount": usdt_amount,
        "sell_quantity": sell_quantity,
        "price_from_webhook": price_from_webhook,
        "sell_percentage": sell_percentage,
        "firebase_average_price": durchschnittspreis,
        "firebase_all_prices": kaufpreise,
        "usdt_balance_before_order": available_usdt,
        "stop_loss_price": stop_loss_price if liquidation_price else None,
        "stop_loss_response": stop_loss_response if liquidation_price else None,
        "saved_usdt_amount": saved_usdt_amounts,      
        "status_fuer_alle": status_fuer_alle.get(base_asset, "Unbekannt"),
        "logs": logs
    })

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)

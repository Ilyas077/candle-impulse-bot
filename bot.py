import os
import time
import base64
import datetime
import requests
import pandas as pd

# --- 1. НАСТРОЙКИ ---
TG_TOKEN = os.environ.get("TG_TOKEN")
TG_CHAT_ID = "531386055"

SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", 
    "UNIUSDT", "AVAXUSDT", "SUIUSDT", "INJUSDT", 
    "AAVEUSDT", "JTOUSDT", "ENAUSDT", "TAOUSDT"
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json"
}

BV_URL = base64.b64decode("aHR0cHM6Ly9kYXRhLWFwaS5iaW5hbmNlLnZpc2lvbi9hcGkvdjMva2xpbmVz").decode()
CB_BASE = base64.b64decode("aHR0cHM6Ly9hcGkuZXhjaGFuZ2UuY29pbmJhc2UuY29tL3Byb2R1Y3RzLw==").decode()
TG_API_BASE = base64.b64decode("aHR0cHM6Ly9hcGkudGVsZWdyYW0ub3JnL2JvdA==").decode()

# --- 2. ОТПРАВКА В TELEGRAM ---
def send_telegram(message):
    if not TG_TOKEN:
        print("ОШИБКА: TG_TOKEN пустой!")
        return
    url = f"{TG_API_BASE}{TG_TOKEN.strip()}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": TG_CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=10)
        if r.status_code != 200:
            print(f"Ошибка Telegram API: {r.text}")
    except Exception as e:
        print(f"Сбой отправки: {e}")

# --- 3. ПОЛУЧЕНИЕ СВЕЧЕЙ (15M И 30M) ---
def get_candles(symbol, timeframe="15m", limit=50):
    try:
        r_bv = requests.get(BV_URL, params={"symbol": symbol, "interval": timeframe, "limit": limit}, headers=HEADERS, timeout=10)
        if r_bv.status_code == 200:
            data_bv = r_bv.json()
            if isinstance(data_bv, list) and len(data_bv) >= 30:
                df = pd.DataFrame([row[:6] for row in data_bv], columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                for col in ['open', 'high', 'low', 'close', 'volume']:
                    df[col] = df[col].astype(float)
                return df
    except Exception:
        pass

    coin = symbol.replace("USDT", "")
    url_cb = f"{CB_BASE}{coin}-USD/candles"
    try:
        r = requests.get(url_cb, params={"granularity": 900}, headers=HEADERS, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list) and len(data) >= 30:
                df = pd.DataFrame(data[:limit*2], columns=['timestamp', 'low', 'high', 'open', 'close', 'volume'])
                df = df.iloc[::-1].reset_index(drop=True)
                for col in ['open', 'high', 'low', 'close', 'volume']:
                    df[col] = df[col].astype(float)
                if timeframe == "15m":
                    return df.tail(limit).reset_index(drop=True)
                elif timeframe == "30m":
                    df['dt'] = pd.to_datetime(df['timestamp'], unit='s')
                    df.set_index('dt', inplace=True)
                    df_30 = df.resample('30min').agg({
                        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
                    }).dropna().reset_index()
                    return df_30.tail(limit).reset_index(drop=True)
    except Exception:
        pass

    return None

# --- 4. РАСЧЕТ ПОЛОС БОЛЛИНДЖЕРА И RSI ---
def add_reversal_indicators(df):
    df['sma20'] = df['close'].rolling(window=20).mean()
    std20 = df['close'].rolling(window=20).std()
    df['bb_upper'] = df['sma20'] + (std20 * 2.1)
    df['bb_lower'] = df['sma20'] - (std20 * 2.1)

    delta = df['close'].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    rs = avg_gain / avg_loss
    df['rsi'] = 100 - (100 / (1 + rs))

    return df

# --- 5. ПОИСК РАЗВОРОТА С САМОГО ДНА ИЛИ ВЕРШИНЫ ---
def check_reversal(symbol, timeframe):
    df = get_candles(symbol, timeframe=timeframe, limit=50)
    if df is None or len(df) < 25:
        return None

    df = add_reversal_indicators(df)
    
    curr = df.iloc[-2]
    prev = df.iloc[-3]
    price = curr['close']
    rsi = round(curr['rsi'], 1)

    body = abs(curr['close'] - curr['open'])
    lower_wick = min(curr['open'], curr['close']) - curr['low']
    upper_wick = curr['high'] - max(curr['open'], curr['close'])

    # --- ЛОНГ С САМОГО НИЗА ---
    touched_bottom = (curr['low'] <= curr['bb_lower']) or (prev['close'] <= prev['bb_lower'])
    bullish_rejection = (curr['close'] > curr['open']) or (lower_wick > body * 1.2)

    if touched_bottom and rsi <= 33 and bullish_rejection:
        sl = round(min(curr['low'], prev['low']) * 0.997, 4)
        tp = round(curr['sma20'], 4)
        if (tp - price) / price < 0.008:
            tp = round(price * 1.015, 4)

        return (
            f"🧲🟢 <b>ЛОВЕЦ ДНА — ЛОНГ ({timeframe})</b>\n\n"
            f"🪙 Монета: <b>#{symbol}</b>\n"
            f"💵 Вход (откуп снизу): <code>{round(price, 4)}</code>\n"
            f"🛡️ Стоп (за тень дна): <code>{sl}</code>\n"
            f"💰 Тейк (к центру канала): <code>{tp}</code>\n\n"
            f"📊 RSI: <b>{rsi}</b> (перепроданность)\n"
            f"💡 <i>Снята нижняя ликвидность за каналом Боллинджера, пошел откуп.</i>"
        )

    # --- ШОРТ С САМОГО ВЕРХА ---
    touched_top = (curr['high'] >= curr['bb_upper']) or (prev['close'] >= prev['bb_upper'])
    bearish_rejection = (curr['close'] < curr['open']) or (upper_wick > body * 1.2)

    if touched_top and rsi >= 67 and bearish_rejection:
        sl = round(max(curr['high'], prev['high']) * 1.003, 4)
        tp = round(curr['sma20'], 4)
        if (price - tp) / price < 0.008:
            tp = round(price * 0.985, 4)

        return (
            f"🧲🔴 <b>ЛОВЕЦ ПИКА — ШОРТ ({timeframe})</b>\n\n"
            f"🪙 Монета: <b>#{symbol}</b>\n"
            f"💵 Вход (отбой сверху): <code>{round(price, 4)}</code>\n"
            f"🛡️ Стоп (за тень пика): <code>{sl}</code>\n"
            f"💰 Тейк (к центру канала): <code>{tp}</code>\n\n"
            f"📊 RSI: <b>{rsi}</b> (перекупленность)\n"
            f"💡 <i>Прокол верхней границы канала, началась фиксация прибыли.</i>"
        )

    return None

# --- 6. ЗАПУСК ---
if __name__ == "__main__":
    current_minute = datetime.datetime.now().minute
    is_manual = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"

    if is_manual:
        send_telegram("🧲 <b>Бот «Ловец Дна и Пиков» (15m / 30m) снова в строю!</b>")

    found = 0
    check_30m_now = (current_minute < 15) or (30 <= current_minute < 45) or is_manual

    for symbol in SYMBOLS:
        msg_15 = check_reversal(symbol, "15m")
        if msg_15:
            send_telegram(msg_15)
            found += 1
        
        if check_30m_now:
            msg_30 = check_reversal(symbol, "30m")
            if msg_30:
                send_telegram(msg_30)
                found += 1
                
        time.sleep(0.3)

    if is_manual and found == 0:
        send_telegram("🧲 Проверка 12 монет завершена. Сейчас цены внутри каналов, крайних пиков для разворота нет.")

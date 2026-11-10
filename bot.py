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
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "INJUSDT", 
    "SUIUSDT", "XRPUSDT", "AVAXUSDT", "TAOUSDT", 
    "HYPEUSDT", "ENAUSDT", "JTOUSDT", "AAVEUSDT"
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json"
}

CB_BASE = base64.b64decode("aHR0cHM6Ly9hcGkuZXhjaGFuZ2UuY29pbmJhc2UuY29tL3Byb2R1Y3RzLw==").decode()
BV_URL = base64.b64decode("aHR0cHM6Ly9kYXRhLWFwaS5iaW5hbmNlLnZpc2lvbi9hcGkvdjMva2xpbmVz").decode()
TG_API_BASE = base64.b64decode("aHR0cHM6Ly9hcGkudGVsZWdyYW0ub3JnL2JvdA==").decode()

# --- 2. ОТПРАВКА В TELEGRAM ---
def send_telegram(message):
    if not TG_TOKEN:
        print("Ошибка: Токен не найден в Secrets!")
        return
    url = f"{TG_API_BASE}{TG_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": TG_CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=10)
        if r.status_code != 200:
            print(f"Ошибка Telegram API: {r.text}")
    except Exception as e:
        print(f"Сбой отправки: {e}")

# --- 3. ПОЛУЧЕНИЕ СВЕЧЕЙ (15M И 30M) ---
def get_candles(symbol, timeframe="15m", limit=20):
    coin = symbol.replace("USDT", "")
    
    # Канал 1: Coinbase (поддерживает 15m; для 30m склеиваем из 15m)
    url_cb = f"{CB_BASE}{coin}-USD/candles"
    try:
        r = requests.get(url_cb, params={"granularity": 900}, headers=HEADERS, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list) and len(data) >= 15:
                df = pd.DataFrame(data[:limit*2], columns=['timestamp', 'low', 'high', 'open', 'close', 'volume'])
                df = df.iloc[::-1].reset_index(drop=True)
                for col in ['open', 'high', 'low', 'close']:
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

    # Канал 2: Зеркало Binance Vision
    try:
        r_bv = requests.get(BV_URL, params={"symbol": symbol, "interval": timeframe, "limit": limit}, headers=HEADERS, timeout=10)
        if r_bv.status_code == 200:
            data_bv = r_bv.json()
            if isinstance(data_bv, list) and len(data_bv) >= 10:
                df = pd.DataFrame([row[:6] for row in data_bv], columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                for col in ['open', 'high', 'low', 'close']:
                    df[col] = df[col].astype(float)
                return df
    except Exception:
        pass

    return None

# --- 4. ПРОВЕРКА 3 ПОСЛЕДОВАТЕЛЬНЫХ СВЕЧЕЙ ---
def check_3_candles(symbol, timeframe):
    df = get_candles(symbol, timeframe=timeframe, limit=15)
    if df is None or len(df) < 5:
        return None

    c1 = df.iloc[-4]
    c2 = df.iloc[-3]
    c3 = df.iloc[-2]

    # ЛОНГ (3 зеленые свечи подряд, каждая закрывается выше предыдущей)
    is_3_green = (c1['close'] > c1['open']) and (c2['close'] > c2['open']) and (c3['close'] > c3['open'])
    higher_closes = (c3['close'] > c2['close']) and (c2['close'] > c1['close'])

    if is_3_green and higher_closes:
        price = c3['close']
        move_pct = round(((price - c1['open']) / c1['open']) * 100, 2)
        return (
            f"🟩🟩🟩 <b>3 СВЕЧИ ВВЕРХ — ЛОНГ ({timeframe})</b>\n\n"
            f"🪙 Монета: <b>#{symbol}</b>\n"
            f"💵 Текущая цена: <code>{round(price, 4)}</code>\n"
            f"📈 Импульс за 3 свечи: <b>+{move_pct}%</b>\n"
            f"🛡️ Ориентир стопа (за 2-ю свечу): <code>{round(c2['low'], 4)}</code>"
        )

    # ШОРТ (3 красные свечи подряд, каждая закрывается ниже предыдущей)
    is_3_red = (c1['close'] < c1['open']) and (c2['close'] < c2['open']) and (c3['close'] < c3['open'])
    lower_closes = (c3['close'] < c2['close']) and (c2['close'] < c1['close'])

    if is_3_red and lower_closes:
        price = c3['close']
        move_pct = round(((c1['open'] - price) / c1['open']) * 100, 2)
        return (
            f"🟥🟥🟥 <b>3 СВЕЧИ ВНИЗ — ШОРТ ({timeframe})</b>\n\n"
            f"🪙 Монета: <b>#{symbol}</b>\n"
            f"💵 Текущая цена: <code>{round(price, 4)}</code>\n"
            f"📉 Импульс за 3 свечи: <b>-{move_pct}%</b>\n"
            f"🛡️ Ориентир стопа (за 2-ю свечу): <code>{round(c2['high'], 4)}</code>"
        )

    return None

# --- 5. ЗАПУСК ---
if __name__ == "__main__":
    print("Запуск свечного сканера (15m и 30m)...")
    current_minute = datetime.datetime.now().minute
    is_manual = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"

    if is_manual:
        send_telegram("🕯️ <b>Свечной бот (15m / 30m) запущен!</b> Ищу серии из 3 свечей...")

    found = 0
    check_30m_now = (current_minute < 15) or (30 <= current_minute < 45) or is_manual

    for symbol in SYMBOLS:
        msg_15 = check_3_candles(symbol, "15m")
        if msg_15:
            send_telegram(msg_15)
            found += 1
        
        if check_30m_now:
            msg_30 = check_3_candles(symbol, "30m")
            if msg_30:
                send_telegram(msg_30)
                found += 1
                
        time.sleep(0.5)

    if is_manual and found == 0:
        send_telegram("🕯️ Проверка 15m и 30m завершена. Сейчас ни по одной монете нет серии из 3 свечей подряд.")
    
    print(f"Сканирование завершено. Найдено сигналов: {found}")

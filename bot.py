import os, time, datetime, requests
import pandas as pd
import numpy as np

TG_TOKEN = "".join((os.environ.get("TG_TOKEN") or "").split())
TG_CHAT_ID = "".join((os.environ.get("TG_CHAT_ID") or "531386055").split())

SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT",
    "UNIUSDT", "AVAXUSDT", "SUIUSDT", "INJUSDT",
    "AAVEUSDT", "JTOUSDT", "ENAUSDT", "TAOUSDT"
]

HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
BV_URL = "https:" + "//data-api.binance.vision" + "/api/v3/klines"
CB_BASE = "https:" + "//://coinbase.com" + "/products/"
TG_API = "https:" + "//api.telegram.org" + "/bot"

def send_telegram(message):
    if not TG_TOKEN or not TG_CHAT_ID:
        print("ОШИБКА: не заданы TG_TOKEN или TG_CHAT_ID!")
        return
    try:
        r = requests.post(TG_API + TG_TOKEN + "/sendMessage", json={"chat_id": TG_CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=10)
        print(f"TG {r.status_code}: {r.text[:80]}")
    except Exception as e:
        print(f"Сбой отправки: {e}")

def get_candles(symbol, timeframe="15m", limit=60):
    try:
        r_bv = requests.get(BV_URL, params={"symbol": symbol, "interval": timeframe, "limit": limit}, headers=HEADERS, timeout=10)
        if r_bv.status_code == 200 and isinstance(r_bv.json(), list) and len(r_bv.json()) >= 30:
            df = pd.DataFrame([row[:6] for row in r_bv.json()], columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            for col in ['open', 'high', 'low', 'close', 'volume']: df[col] = df[col].astype(float)
            return df
    except Exception: pass

    coin = symbol.replace("USDT", "")
    url_cb = f"{CB_BASE}{coin}-USD/candles"
    try:
        gran = 3600 if timeframe == "1h" else 900
        req_lim = limit if timeframe in ("15m", "1h") else limit * 2
        r = requests.get(url_cb, params={"granularity": gran}, headers=HEADERS, timeout=10)
        if r.status_code == 200 and isinstance(r.json(), list) and len(r.json()) >= 30:
            df = pd.DataFrame(r.json()[:req_lim], columns=['timestamp', 'low', 'high', 'open', 'close', 'volume']).iloc[::-1].reset_index(drop=True)
            for col in ['open', 'high', 'low', 'close', 'volume']: df[col] = df[col].astype(float)
            if timeframe in ("15m", "1h"): return df.tail(limit).reset_index(drop=True)
            df['dt'] = pd.to_datetime(df['timestamp'], unit='s')
            return df.set_index('dt').resample('30min').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}).dropna().reset_index().tail(limit).reset_index(drop=True)
    except Exception: pass
    return None

def get_1h_adx(symbol):
    df = get_candles(symbol, "1h", limit=50)
    if df is None or len(df) < 30: return 20.0
    h, l, c = df['high'], df['low'], df['close']
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    plus_dm = np.where(h.diff().clip(lower=0) > (-l.diff()).clip(lower=0), h.diff().clip(lower=0), 0.0)
    minus_dm = np.where((-l.diff()).clip(lower=0) > h.diff().clip(lower=0), (-l.diff()).clip(lower=0), 0.0)
    atr = tr.ewm(alpha=1/14, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm).ewm(alpha=1/14, adjust=False).mean() / atr
    minus_di = 100 * pd.Series(minus_dm).ewm(alpha=1/14, adjust=False).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1)
    return round(float(dx.ewm(alpha=1/14, adjust=False).mean().iloc[-2]), 1)

def add_reversal_indicators(df):
    df['sma20'] = df['close'].rolling(20).mean()
    std20 = df['close'].rolling(20).std()
    df['bb_upper'] = df['sma20'] + (std20 * 2.1)
    df['bb_lower'] = df['sma20'] - (std20 * 2.1)
    delta = df['close'].diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    df['rsi'] = 100 - (100 / (1 + (gain / loss)))
    return df

def check_reversal(symbol, timeframe, adx_1h):
    if adx_1h >= 32: return None
    df = get_candles(symbol, timeframe=timeframe, limit=50)
    if df is None or len(df) < 25: return None

    df = add_reversal_indicators(df)
    curr, prev = df.iloc[-2], df.iloc[-3]
    price, rsi = curr['close'], round(curr['rsi'], 1)
    body = abs(curr['close'] - curr['open'])
    lower_wick = min(curr['open'], curr['close']) - curr['low']
    upper_wick = curr['high'] - max(curr['open'], curr['close'])

    touched_bottom = (curr['low'] <= curr['bb_lower']) or (prev['close'] <= prev['bb_lower'])
    bullish_rej = (curr['close'] > curr['open']) or (lower_wick > body * 1.2)
    if touched_bottom and rsi <= 30 and bullish_rej:
        sl = round(min(curr['low'], prev['low']) * 0.997, 4)
        tp = round(curr['sma20'], 4)
        if (tp - price) / price < 0.008: tp = round(price * 1.015, 4)
        return (
            f"🧲🟢 <b>ЛОВЕЦ ДНА — ЛОНГ ({timeframe})</b>\n\n"
            f"🪙 Монета: <b>#{symbol}</b>\n"
            f"💵 Вход: <code>{round(price, 4)}</code>\n"
            f"🛡️ Стоп: <code>{sl}</code>\n"
            f"💰 Тейк: <code>{tp}</code>\n\n"
            f"📊 RSI: <b>{rsi}</b> | ADX 1H: <b>{adx_1h}</b> (флэт)\n"
            f"💡 <i>Снята нижняя граница Боллинджера, пошел откуп.</i>"
        )

    touched_top = (curr['high'] >= curr['bb_upper']) or (prev['close'] >= prev['bb_upper'])
    bearish_rej = (curr['close'] < curr['open']) or (upper_wick > body * 1.2)
    if touched_top and rsi >= 70 and bearish_rej:
        sl = round(max(curr['high'], prev['high']) * 1.003, 4)
        tp = round(curr['sma20'], 4)
        if (price - tp) / price < 0.008: tp = round(price * 0.985, 4)
        return (
            f"🧲🔴 <b>ЛОВЕЦ ПИКА — ШОРТ ({timeframe})</b>\n\n"
            f"🪙 Монета: <b>#{symbol}</b>\n"
            f"💵 Вход: <code>{round(price, 4)}</code>\n"
            f"🛡️ Стоп: <code>{sl}</code>\n"
            f"💰 Тейк: <code>{tp}</code>\n\n"
            f"📊 RSI: <b>{rsi}</b> | ADX 1H: <b>{adx_1h}</b> (флэт)\n"
            f"💡 <i>Прокол верхней границы Боллинджера, пошел отбой.</i>"
        )
    return None

if __name__ == "__main__":
    now_min = datetime.datetime.now(datetime.timezone.utc).minute
    is_manual = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
    check_30m = (now_min % 30 < 15) or is_manual
    found = 0

    for symbol in SYMBOLS:
        adx_1h = get_1h_adx(symbol)
        for tf in (["15m", "30m"] if check_30m else ["15m"]):
            msg = check_reversal(symbol, tf, adx_1h)
            if msg:
                send_telegram(msg)
                found += 1
        time.sleep(0.4)

    if is_manual and found == 0:
        send_telegram("🧲 <b>Ловец Дна и Пиков (15m/30m + ADX)</b>: проверка 12 монет завершена, крайних пиков во флэте сейчас нет.")

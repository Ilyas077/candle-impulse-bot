import os
import time
import datetime
import requests

# --- 1. НАСТРОЙКИ (ИЗ ВАШЕГО СТАРОГО КОДА) ---
TG_TOKEN = os.environ.get("TG_TOKEN")
TG_CHAT_ID = "531386055"

SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", 
    "UNIUSDT", "AVAXUSDT", "SUIUSDT", "INJUSDT", 
    "AAVEUSDT", "JTOUSDT", "ENAUSDT", "TAOUSDT"
]

TIMEFRAME = "5m"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json"
}

# --- 2. ОТПРАВКА В TELEGRAM ---
def send_telegram(message):
    if not TG_TOKEN:
        print("Токен не найден. Сообщение:", message)
        return
    url = f"https://telegram.org{TG_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TG_CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        print(f"Сбой отправки: {e}")

# --- 3. СБОР 6 ПАРАМЕТРОВ (BINANCE С РЕЗЕРВОМ НА BYBIT) ---
def get_6_metrics(symbol):
    # Попытка 1: Binance Futures + Spot
    try:
        fapi = "https://binance.com"
        spot = "https://binance.com"
        
        # 1. Свечи фьючерсов (60 штук = 5 часов для поиска локального дна/пика)
        r_fk = requests.get(f"{fapi}/fapi/v1/klines", params={"symbol": symbol, "interval": TIMEFRAME, "limit": 60}, headers=HEADERS, timeout=8)
        if r_fk.status_code == 200:
            fk = r_fk.json()
            
            highs = [float(k[2]) for k in fk[:-1]]
            lows = [float(k[3]) for k in fk[:-1]]
            max_p, min_p = max(highs), min(lows)
            
            c_prev = fk[-3]
            c_last = fk[-2]
            
            open_p = float(c_last[1])
            close_p = float(c_last[4])
            price_pos = (close_p - min_p) / (max_p - min_p) if max_p != min_p else 0.5

            # 2. Фьючерсная дельта (CVD)
            def calc_delta(k):
                tot_v = float(k[7]) # Объем в USDT
                buy_v = float(k[10]) # Покупки по рынку в USDT
                return buy_v - (tot_v - buy_v)

            f_delta_prev = calc_delta(c_prev)
            f_delta_last = calc_delta(c_last)

            # 3. Спотовая дельта (CVD спота)
            r_sk = requests.get(f"{spot}/api/v3/klines", params={"symbol": symbol, "interval": TIMEFRAME, "limit": 3}, headers=HEADERS, timeout=8).json()
            s_delta_last = calc_delta(r_sk[-2])

            # 4. Открытый интерес (OI)
            r_oi = requests.get(f"{fapi}/futures/data/openInterestHist", params={"symbol": symbol, "period": TIMEFRAME, "limit": 2}, headers=HEADERS, timeout=8).json()
            oi_prev = float(r_oi[-2]["sumOpenInterest"])
            oi_last = float(r_oi[-1]["sumOpenInterest"])
            oi_diff_pct = ((oi_last - oi_prev) / oi_prev) * 100

            # 5. Стакан ордеров (Биды и Аски топ-50)
            r_ob = requests.get(f"{fapi}/fapi/v1/depth", params={"symbol": symbol, "limit": 50}, headers=HEADERS, timeout=8).json()
            bids_usdt = sum(float(b[0]) * float(b[1]) for b in r_ob["bids"])
            asks_usdt = sum(float(a[0]) * float(a[1]) for a in r_ob["asks"])
            ob_ratio = bids_usdt / asks_usdt if asks_usdt > 0 else 1.0

            # 6. Ставка финансирования (Funding Rate)
            r_fr = requests.get(f"{fapi}/fapi/v1/premiumIndex", params={"symbol": symbol}, headers=HEADERS, timeout=8).json()
            funding = float(r_fr["lastFundingRate"]) * 100

            # Локальные экстремумы за 1 час (12 свечей) для стопа
            recent_low = min([float(k[3]) for k in fk[-13:-1]])
            recent_high = max([float(k[2]) for k in fk[-13:-1]])

            return {
                "source": "Binance",
                "price": close_p,
                "pos": price_pos,
                "is_green": close_p > open_p,
                "f_delta_prev": f_delta_prev,
                "f_delta_last": f_delta_last,
                "s_delta": s_delta_last,
                "oi_diff": oi_diff_pct,
                "ob_ratio": ob_ratio,
                "funding": funding,
                "recent_low": recent_low,
                "recent_high": recent_high
            }
    except Exception:
        pass

    # Попытка 2: Резерв через Bybit V5 API (если сервер GitHub в США и Binance заблокирован)
    try:
        bybit = "https://bybit.com"
        r_bk = requests.get(f"{bybit}/v5/market/kline", params={"category": "linear", "symbol": symbol, "interval": "5", "limit": 60}, headers=HEADERS, timeout=8).json()
        if r_bk.get("retCode") == 0:
            # Bybit отдает свечи от новых к старым, переворачиваем
            bk = r_bk["result"]["list"][::-1]
            highs = [float(k[2]) for k in bk[:-1]]
            lows = [float(k[3]) for k in bk[:-1]]
            max_p, min_p = max(highs), min(lows)
            
            c_prev = bk[-3]
            c_last = bk[-2]
            open_p, close_p = float(c_last[1]), float(c_last[4])
            price_pos = (close_p - min_p) / (max_p - min_p) if max_p != min_p else 0.5

            # Оценка дельты по направлению и объему свечи
            f_delta_prev = float(c_prev[6]) if float(c_prev[4]) > float(c_prev[1]) else -float(c_prev[6])
            f_delta_last = float(c_last[6]) if close_p > open_p else -float(c_last[6])

            # Спот Bybit
            r_bsk = requests.get(f"{bybit}/v5/market/kline", params={"category": "spot", "symbol": symbol, "interval": "5", "limit": 3}, headers=HEADERS, timeout=8).json()
            sc_last = r_bsk["result"]["list"][1]
            s_delta_last = float(sc_last[6]) if float(sc_last[4]) >= float(sc_last[1]) else -float(sc_last[6])

            # Открытый интерес Bybit
            r_boi = requests.get(f"{bybit}/v5/market/open-interest", params={"category": "linear", "symbol": symbol, "intervalTime": "5min", "limit": 2}, headers=HEADERS, timeout=8).json()
            oi_list = r_boi["result"]["list"]
            oi_diff_pct = ((float(oi_list[0]["openInterest"]) - float(oi_list[1]["openInterest"])) / float(oi_list[1]["openInterest"])) * 100

            # Стакан Bybit
            r_bob = requests.get(f"{bybit}/v5/market/orderbook", params={"category": "linear", "symbol": symbol, "limit": 50}, headers=HEADERS, timeout=8).json()
            bids_usdt = sum(float(b[0]) * float(b[1]) for b in r_bob["result"]["b"])
            asks_usdt = sum(float(a[0]) * float(a[1]) for a in r_bob["result"]["a"])
            ob_ratio = bids_usdt / asks_usdt if asks_usdt > 0 else 1.0

            # Фандинг Bybit
            r_bfr = requests.get(f"{bybit}/v5/market/tickers", params={"category": "linear", "symbol": symbol}, headers=HEADERS, timeout=8).json()
            funding = float(r_bfr["result"]["list"][0]["fundingRate"]) * 100

            recent_low = min([float(k[3]) for k in bk[-13:-1]])
            recent_high = max([float(k[2]) for k in bk[-13:-1]])

            return {
                "source": "Bybit",
                "price": close_p,
                "pos": price_pos,
                "is_green": close_p > open_p,
                "f_delta_prev": f_delta_prev,
                "f_delta_last": f_delta_last,
                "s_delta": s_delta_last,
                "oi_diff": oi_diff_pct,
                "ob_ratio": ob_ratio,
                "funding": funding,
                "recent_low": recent_low,
                "recent_high": recent_high
            }
    except Exception:
        pass

    return None

# --- 4. ПРОВЕРКА СОВПАДЕНИЯ ВСЕХ 6 ПАРАМЕТРОВ ---
def check_coinglass_setup(symbol):
    d = get_6_metrics(symbol)
    if not d:
        return None

    price = d["price"]

    # --- ЛОНГ (Все 6 факторов сошлись на развороте снизу) ---
    long_cond = (
        d["pos"] <= 0.25 and               # 1. Цена в нижней 25% зоне 5-часового диапазона
        d["is_green"] and                  # 1.1 Закрылась бычья 5-минутка
        d["f_delta_prev"] < 0 and          # 2. До этого фьючерсный CVD падал
        d["f_delta_last"] > 0 and          # 2.1 На последней свече пошел откуп по рынку
        d["s_delta"] >= 0 and              # 3. Спот поддерживает (нет продаж на споте)
        d["oi_diff"] > 0.03 and            # 4. Открытый интерес растет (набор лонгов)
        d["ob_ratio"] > 1.15 and           # 5. В стакане бидов больше асков на 15%+
        d["funding"] < 0.015               # 6. Нет перегрева лонгов по фандингу
    )

    if long_cond:
        sl = round(d["recent_low"] * 0.997, 4)
        risk = price - sl
        if risk <= 0:
            sl = round(price * 0.992, 4)
            risk = price - sl
        tp = round(price + (risk * 2.5), 4)

        return (
            f"🟢 <b>ПОДТВЕРЖДЕННЫЙ ЛОНГ ({TIMEFRAME}) — #{symbol}</b>\n\n"
            f"💵 Вход: <code>{round(price, 4)}</code>\n"
            f"🛡️ Стоп: <code>{sl}</code> (-{round((risk/price)*100, 2)}%)\n"
            f"💰 Тейк: <code>{tp}</code> (+{round(((tp-price)/price)*100, 2)}%)\n\n"
            f"📊 <b>6/6 метрик ({d['source']}):</b>\n"
            f"• Позиция в канале: <b>{round(d['pos']*100)}%</b> (дно)\n"
            f"• Фьюч. CVD 5м: <b>+{round(d['f_delta_last']/1000, 1)}K$</b> (разворот)\n"
            f"• Спот CVD 5м: <b>+{round(d['s_delta']/1000, 1)}K$</b>\n"
            f"• Открытый интерес: <b>+{round(d['oi_diff'], 2)}%</b>\n"
            f"• Стакан (Bid/Ask): <b>{round(d['ob_ratio'], 2)}</b>\n"
            f"• Фандинг: <b>{round(d['funding'], 4)}%</b>"
        )

    # --- ШОРТ (Все 6 факторов сошлись на развороте сверху) ---
    short_cond = (
        d["pos"] >= 0.75 and               # 1. Цена в верхней 25% зоне 5-часового диапазона
        not d["is_green"] and              # 1.1 Закрылась медвежья 5-минутка
        d["f_delta_prev"] > 0 and          # 2. До этого фьючерсный CVD рос
        d["f_delta_last"] < 0 and          # 2.1 На последней свече пошли рыночные продажи
        d["s_delta"] <= 0 and              # 3. Спот подтверждает продажи
        d["oi_diff"] > 0.03 and            # 4. Открытый интерес растет (набор шортов)

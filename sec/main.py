import os, time, math, csv, pathlib, threading, random
from typing import List, Optional
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests
import numpy as np
from dotenv import load_dotenv

# ---------------- Config ----------------
load_dotenv()
PAPER_MODE = (os.getenv("PAPER_MODE", "true").lower() == "true")
PRODUCT = os.getenv("PRODUCT", "BTC-USD")
GRANULARITY = int(os.getenv("GRANULARITY", "60"))
POLL_SEC = int(os.getenv("POLL_SEC", "10"))

START_CASH = float(os.getenv("START_CASH", "100.0"))
RISK_PCT = float(os.getenv("RISK_PCT", "0.01"))
ATR_LEN = int(os.getenv("ATR_LEN", "14"))
ATR_MULT = float(os.getenv("ATR_MULT", "2.0"))
LOSS_STREAK_PAUSE = int(os.getenv("LOSS_STREAK_PAUSE", "5"))
COOLDOWN_BARS = int(os.getenv("COOLDOWN_BARS", "3"))
MIN_TRADE_USD = float(os.getenv("MIN_TRADE_USD", "5.0"))
MAX_POSITION_USD = float(os.getenv("MAX_POSITION_USD", "50.0"))
SESSION_MAX_DRAWDOWN_USD = float(os.getenv("SESSION_MAX_DRAWDOWN_USD", "15.0"))

HEALTH_PORT = int(os.getenv("HEALTH_PORT", "8080"))
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID", "")

if not PAPER_MODE:
    for k in ("COINBASE_API_KEY", "COINBASE_API_SECRET", "COINBASE_API_PASSPHRASE"):
        assert os.getenv(k), f"Missing {k} in .env for live mode."

BROKERAGE = "https://api.coinbase.com/api/v3/brokerage"

DATA_DIR = pathlib.Path("data"); DATA_DIR.mkdir(exist_ok=True)
TRADE_CSV = DATA_DIR / "trades.csv"
if not TRADE_CSV.exists():
    with open(TRADE_CSV, "w", newline="") as f:
        csv.writer(f).writerow(["t","event","price","qty","pnl","equity"])

def now() -> datetime:
    return datetime.now(timezone.utc)

def ts(dt: datetime) -> int:
    return int(dt.timestamp())

def tg(msg: str):
    if not TG_TOKEN or not TG_CHAT: return
    try:
        requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                      json={"chat_id": TG_CHAT, "text": msg[:4000]}, timeout=10)
    except Exception:
        pass

def start_healthcheck(port: int):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/health":
                self.send_response(200); self.end_headers(); self.wfile.write(b"ok"); return
            self.send_response(404); self.end_headers()
    t = threading.Thread(target=lambda: HTTPServer(("0.0.0.0", port), H).serve_forever(),
                         daemon=True)
    t.start()

def http_get(url: str, params: dict, timeout=30, tries=5, backoff=2.0):
    """GET with simple exponential backoff."""
    last_err = None
    for i in range(tries):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            r.raise_for_status()
            return r
        except Exception as e:
            last_err = e
            sleep = backoff ** i + random.random()
            time.sleep(sleep)
    raise last_err

@dataclass
class Candle:
    start: int; low: float; high: float; open: float; close: float; volume: float

def get_candles(product: str, granularity: int, lookback_minutes: int=240) -> List[Candle]:
    end_dt = now()
    start_dt = end_dt - timedelta(minutes=lookback_minutes)
    r = http_get(f"{BROKERAGE}/products/{product}/candles",
                 params={"start": ts(start_dt), "end": ts(end_dt), "granularity": granularity})
    data = r.json().get("candles", [])
    data.sort(key=lambda x: x["start"])
    return [Candle(**c) for c in data]

def sma(values: List[float], n: int) -> Optional[float]:
    if len(values) < n: return None
    return float(sum(values[-n:]) / n)

def compute_atr(highs: List[float], lows: List[float], closes: List[float], n: int) -> Optional[float]:
    if len(closes) < n+1: return None
    tr = []
    for i in range(-n, 0):
        h = highs[i]; l = lows[i]; pc = closes[i-1]
        tr.append(max(h-l, abs(h-pc), abs(l-pc)))
    return float(sum(tr) / n)

@dataclass
class Position:
    qty: float
    entry: float
    stop: float
    tp: Optional[float]

@dataclass
class Paper:
    cash: float
    asset: float = 0.0
    fees: float = 0.0
    pos: Optional[Position] = None
    losses_in_row: int = 0
    cooldown_left: int = 0
    session_peak_equity: float = 0.0
    session_paused: bool = False

    def _fee(self, notional: float) -> float:
        fee = notional * 0.0005
        self.fees += fee
        return fee

    def equity(self, mark: float) -> float:
        eq = self.cash + self.asset * mark
        if eq > self.session_peak_equity:
            self.session_peak_equity = eq
        # session drawdown pause
        if (self.session_peak_equity - eq) >= SESSION_MAX_DRAWDOWN_USD:
            self.session_paused = True
        return eq

    def buy_usd(self, price: float, usd: float) -> float:
        fee = self._fee(usd)
        usd_net = usd - fee
        qty = usd_net / price
        self.cash -= usd
        self.asset += qty
        return qty

    def sell_qty(self, price: float, qty: float) -> float:
        notional = qty * price
        fee = self._fee(notional)
        proceeds = notional - fee
        self.asset -= qty
        self.cash += proceeds
        return proceeds

def log_trade(event: str, price: float, qty: float, pnl: float, equity: float):
    with open(TRADE_CSV, "a", newline="") as f:
        csv.writer(f).writerow([now().isoformat(), event, f"{price:.2f}", f"{qty:.6f}", f"{pnl:.2f}", f"{equity:.2f}"])

def crossover_signal(closes: List[float]) -> str:
    f = sma(closes, 20); s = sma(closes, 50)
    if f is None or s is None: return "WARMUP"
    # lookback one bar for fresh cross
    f1 = sma(closes[:-1], 20); s1 = sma(closes[:-1], 50)
    if f1 is None or s1 is None: return "WARMUP"
    if f1 <= s1 and f > s: return "BUY"
    if f1 >= s1 and f < s: return "SELL"
    return "HOLD"

def run():
    start_healthcheck(HEALTH_PORT)
    tg("MiniMax: starting ✅")
    print(f"MiniMax | PRODUCT={PRODUCT} TF={GRANULARITY}s PAPER={PAPER_MODE}")
    state = Paper(cash=START_CASH, session_peak_equity=START_CASH)
    last_bar_start = 0

    # prime history
    hist = get_candles(PRODUCT, GRANULARITY, lookback_minutes=300)
    highs = [c.high for c in hist]; lows = [c.low for c in hist]; closes = [c.close for c in hist]
    if hist: last_bar_start = hist[-1].start

    while True:
        try:
            # fetch rolling window to avoid gaps
            new = get_candles(PRODUCT, GRANULARITY, lookback_minutes=180)
            fresh = [c for c in new if c.start > last_bar_start]
            if not fresh:
                time.sleep(POLL_SEC); continue

            for c in fresh:
                highs.append(c.high); lows.append(c.low); closes.append(c.close)
                last_bar_start = c.start

                price = closes[-1]
                eq = state.equity(price)

                # session pause? do nothing except heartbeat
                if state.session_paused:
                    print(f"[{datetime.fromtimestamp(last_bar_start, tz=timezone.utc).isoformat()}] SESSION-PAUSED dd_limit hit | px={price:.2f} eq={eq:.2f}")
                    continue

                # risk controls on open position
                if state.pos:
                    if price <= state.pos.stop:
                        proceeds = state.sell_qty(state.pos.stop, state.pos.qty)
                        pnl = proceeds - (state.pos.qty * state.pos.entry)
                        state.losses_in_row += 1
                        log_trade("STOP", state.pos.stop, state.pos.qty, pnl, state.equity(state.pos.stop))
                        state.pos = None
                        state.cooldown_left = COOLDOWN_BARS
                        print(f"STOP @ {state.pos.stop if state.pos else 0:.2f} | eq={state.equity(price):.2f}")
                        # continue to next bar
                        continue
                    if state.pos.tp and price >= state.pos.tp:
                        proceeds = state.sell_qty(state.pos.tp, state.pos.qty)
                        pnl = proceeds - (state.pos.qty * state.pos.entry)
                        state.losses_in_row = 0
                        log_trade("TP", state.pos.tp, state.pos.qty, pnl, state.equity(state.pos.tp))
                        state.pos = None
                        state.cooldown_left = COOLDOWN_BARS
                        print(f"TP   @ {price:.2f} | eq={state.equity(price):.2f}")
                        continue

                sig = crossover_signal(closes)

                # cooldown & loss-streak gating
                if state.cooldown_left > 0:
                    state.cooldown_left -= 1
                    sig = "HOLD"
                if state.losses_in_row >= LOSS_STREAK_PAUSE:
                    sig = "HOLD"

                if sig == "BUY" and not state.pos:
                    atr_now = compute_atr(highs, lows, closes, ATR_LEN)
                    # fallback if ATR not ready
                    if atr_now is None or atr_now <= 0:
                        stop = price * 0.994
                    else:
                        stop = price - ATR_MULT * atr_now
                        if stop >= price:
                            stop = price * 0.994
                    usd_risk = max(MIN_TRADE_USD, state.equity(price) * RISK_PCT)
                    # size calc
                    risk_per_unit = max(1e-8, price - stop)
                    qty_by_risk = usd_risk / risk_per_unit
                    max_qty_by_cap = (min(MAX_POSITION_USD, state.cash * 0.98)) / price
                    qty = max(0.0, min(qty_by_risk, max_qty_by_cap))
                    if qty > 0:
                        spent = qty * price
                        got = state.buy_usd(price, spent)
                        tp = price * 1.01  # simple 1% TP (tune later)
                        state.pos = Position(qty=got, entry=price, stop=stop, tp=tp)
                        log_trade("BUY", price, got, 0.0, state.equity(price))
                        print(f"BUY  @ {price:.2f} | qty={got:.6f} stop={stop:.2f} tp={tp:.2f} | eq={state.equity(price):.2f}")

                elif sig == "SELL" and state.pos:
                    proceeds = state.sell_qty(price, state.pos.qty)
                    pnl = proceeds - (state.pos.qty * state.pos.entry)
                    state.losses_in_row = 0 if pnl >= 0 else state.losses_in_row + 1
                    log_trade("EXIT", price, state.pos.qty, pnl, state.equity(price))
                    state.pos = None
                    state.cooldown_left = COOLDOWN_BARS
                    print(f"EXIT @ {price:.2f} | pnl={pnl:.2f} | eq={state.equity(price):.2f}")

                status = "FLAT" if not state.pos else f"LONG {state.pos.qty:.6f} @ {state.pos.entry:.2f} stp={state.pos.stop:.2f} tp={state.pos.tp:.2f}"
                print(f"[{datetime.fromtimestamp(last_bar_start, tz=timezone.utc).isoformat()}] px={price:.2f} {status} cash={state.cash:.2f} asset={state.asset:.6f} fees={state.fees:.2f}")

            time.sleep(POLL_SEC)

        except KeyboardInterrupt:
            px = closes[-1] if closes else 0.0
            if state.pos:
                proceeds = state.sell_qty(px, state.pos.qty)
                pnl = proceeds - (state.pos.qty * state.pos.entry)
                log_trade("FORCE_EXIT", px, state.pos.qty, pnl, state.equity(px))
                state.pos = None
            tg("MiniMax: stopped by user 🛑")
            print(f"\nFinal Equity: {state.equity(px):.2f}")
            break
        except Exception as e:
            tg(f"MiniMax crashed: {type(e).__name__}: {e} ❌")
            print(f"[ERR] {type(e).__name__}: {e}")
            time.sleep(max(5, POLL_SEC))

if __name__ == "__main__":
    run()

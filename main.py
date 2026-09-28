"""Local, read-only MT5 companion. No trading operations are implemented."""
import os
import re
import time
import math
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()
try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

app = FastAPI(title="Weltrade Trading Companion")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
lock = Lock()
WATCH = ("XAUUSD", "BTCUSD", "GBPUSD", "EURUSD")
PERIODS = {"M1": "TIMEFRAME_M1", "M5": "TIMEFRAME_M5", "M15": "TIMEFRAME_M15", "H1": "TIMEFRAME_H1", "H4": "TIMEFRAME_H4"}


def connect():
    if mt5 is None:
        raise HTTPException(503, "Install requirements on Windows with MT5 installed.")
    path = os.getenv("MT5_TERMINAL_PATH", "").strip()
    if not (mt5.initialize(path=path) if path else mt5.initialize()):
        raise HTTPException(503, f"MT5 unavailable: {mt5.last_error()}. Open and sign in to your Weltrade MT5 terminal.")


def resolve(base):
    # Prefer exact broker symbol; account types may append suffixes.
    configured = os.getenv(f"MT5_SYMBOL_{base}", "").strip()
    if configured:
        if mt5.symbol_select(configured, True):
            return configured
        raise HTTPException(404, f"Configured symbol {configured} is unavailable. Check MT5_SYMBOL_{base}.")
    names = mt5.symbols_get()
    if names is None:
        raise HTTPException(503, f"Could not list MT5 symbols: {mt5.last_error()}")
    options = [s.name for s in names if re.fullmatch(re.escape(base) + r"(?:[._-]?[A-Za-z0-9]+)?", s.name, re.I)]
    options.sort(key=lambda n: (n.upper() != base, len(n)))
    if len(options) > 1 and options[0].upper() != base:
        raise HTTPException(409, f"Multiple symbols match {base}. Set MT5_SYMBOL_{base} in .env to the Market Watch name.")
    for name in options:
        if mt5.symbol_select(name, True):
            return name
    raise HTTPException(404, f"{base} is unavailable on this account. Check the name in MT5 Market Watch.")


@app.get("/")
def home():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/api/market")
def market():
    with lock:
        connect()
        result = []
        for base in WATCH:
            try:
                name = resolve(base)
                tick = mt5.symbol_info_tick(name)
                if tick is None:
                    raise HTTPException(503, "No tick available")
                if not all(math.isfinite(v) and v > 0 for v in (tick.bid, tick.ask)) or tick.ask < tick.bid:
                    raise HTTPException(503, "Invalid bid/ask quote")
                observed = datetime.fromtimestamp(tick.time_msc / 1000 if tick.time_msc else tick.time, timezone.utc)
                result.append({"base": base, "symbol": name, "bid": tick.bid, "ask": tick.ask,
                               "spread": tick.ask - tick.bid, "time": observed.isoformat(),
                               "age_seconds": max(0, round(time.time() - observed.timestamp(), 1)), "error": None})
            except HTTPException as exc:
                result.append({"base": base, "error": exc.detail})
        return {"server_time": datetime.now(timezone.utc).isoformat(), "symbols": result}


@app.get("/api/candles/{base}")
def candles(base: str, timeframe: str = "M5"):
    base, timeframe = base.upper(), timeframe.upper()
    if base not in WATCH or timeframe not in PERIODS:
        raise HTTPException(400, "Unsupported symbol or timeframe")
    with lock:
        connect()
        symbol = resolve(base)
        rates = mt5.copy_rates_from_pos(symbol, getattr(mt5, PERIODS[timeframe]), 0, 121)
        if rates is None or len(rates) < 20:
            raise HTTPException(503, f"Insufficient {timeframe} history in MT5")
        return {"symbol": symbol, "timeframe": timeframe,
                "candles": [{"time": int(r["time"]), "open": float(r["open"]), "high": float(r["high"]),
                             "low": float(r["low"]), "close": float(r["close"]), "volume": int(r["tick_volume"])}
                            for r in rates]}


class AnalysisRequest(BaseModel):
    symbol: str
    timeframe: str = "M5"
    question: str = "Assess the current market structure and identify what confirmation would be needed for a trade."


@app.post("/api/analyze")
def analyze(request: AnalysisRequest):
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(503, "Set OPENAI_API_KEY in your local .env to enable analysis.")
    if request.symbol.upper() not in WATCH or request.timeframe.upper() not in PERIODS:
        raise HTTPException(400, "Unsupported symbol or timeframe")
    data = candles(request.symbol, request.timeframe)
    quote = market()
    tick = next((s for s in quote["symbols"] if s["base"] == request.symbol.upper()), None)
    if not tick or tick.get("error") or tick["age_seconds"] > 120:
        raise HTTPException(503, "Quote unavailable or older than 120 seconds. Analysis paused.")
    period_seconds = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600, "H4": 14400}[data["timeframe"]]
    if time.time() - data["candles"][-1]["time"] > period_seconds + 120:
        raise HTTPException(503, "Candle history is stale. Analysis paused; refresh history in MT5.")
    import json
    from openai import OpenAI
    # Send compact broker-sourced data. The model has no order execution tool.
    payload = {"broker_quote": tick, "timeframe": data["timeframe"], "candles": data["candles"][-80:],
               "question": request.question[:500]}
    try:
        response = OpenAI().responses.create(
            model=os.getenv("OPENAI_MODEL", "gpt-5.4"),
            instructions=("You are a cautious trading analysis assistant. Use only the supplied broker data. "
                          "Quote timestamps and spread. Explain trend, levels, possible confirmation, invalidation, "
                          "and uncertainty. State when the candles do not support a setup. Do not promise profit, "
                          "invent news, or imply you placed a trade. The last candle is still forming; distinguish it "
                          "from closed-candle confirmation. Never make decisions for the user."),
            input=json.dumps(payload))
        return {"analysis": response.output_text, "quote_time": tick["time"], "symbol": tick["symbol"],
                "timeframe": data["timeframe"]}
    except Exception as exc:
        raise HTTPException(502, f"Analysis service unavailable: {type(exc).__name__}") from exc

"""Explicit synthetic dashboard fixture: python tests/preview_app.py (port 8012)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import time
from dataclasses import replace, asdict
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from test_ta_v1 import snap
from engines.technical import analyze

app = FastAPI()
ROOT = Path(__file__).resolve().parents[1]
app.mount('/static', StaticFiles(directory=ROOT/'static'), name='static')


def fixture(symbol):
    s = snap()
    now = time.time()
    shift = int(now//3600)*3600 - s.as_of_utc
    return replace(s, symbol=symbol+' (SYNTHETIC)', as_of_utc=now,
                   timeframes=tuple(replace(f, candles=tuple(replace(c,time=c.time+shift) for c in f.candles)) for f in s.timeframes),
                   quote=replace(s.quote,time=now))


@app.get('/')
def home():
    return FileResponse(ROOT/'static'/'index.html')


@app.get('/api/technical/{base}')
def technical(base: str):
    return analyze(fixture(base))


@app.get('/api/candles/{base}')
def candles(base: str, timeframe: str = 'M15'):
    s=fixture(base)
    f=next((f for f in s.timeframes if f.timeframe == timeframe),s.timeframes[0])
    return dict(symbol=s.symbol,timeframe=timeframe,candles=[asdict(c) for c in f.candles[-120:]])


@app.get('/api/market')
def market():
    return dict(symbols=[dict(base=b,symbol=b+' (SYNTHETIC)',bid=130,ask=130.02,spread=.02,
                             time=datetime.now(timezone.utc).isoformat(),age_seconds=0,error=None)
                         for b in ('XAUUSD','BTCUSD','GBPUSD','EURUSD')])


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=8012)

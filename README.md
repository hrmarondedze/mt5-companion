# Weltrade MT5 trading companion

A local, read-only dashboard for XAUUSD, BTCUSD, GBPUSD, and EURUSD from your own Weltrade MT5 terminal. It includes optional on-demand AI analysis. It cannot place, change, or close trades.

## Windows setup

1. Install and open **Weltrade MetaTrader 5** on your Windows PC. Log in to your account. Confirm the four symbols appear in **Market Watch**; their broker names may have suffixes.
2. Install Python 3.11 or 3.12 (64-bit), including pip, then open PowerShell inside this folder.
3. Run:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r requirements.txt
   Copy-Item .env.example .env
   python -m uvicorn main:app --host 127.0.0.1 --port 8000
   ```

4. Open http://127.0.0.1:8000 in your browser. If MT5 is not discovered, set `MT5_TERMINAL_PATH` in `.env` to your terminal64.exe path and restart.
5. To enable the Analyze button, create an OpenAI API key in your own account and set `OPENAI_API_KEY` inside your local `.env`. This may incur API charges. Do not send your broker password or API key in chat or commit `.env` to Git.

## What it reads

- Quotes, bid/ask spreads, and tick timestamps from MT5.
- Up to 121 candles on the selected timeframe. The chart shows OHLC candlesticks, including the current forming candle.
- Optional AI explanation sends the versioned technical observation when you press Explain. Local technical analysis refreshes every 30 seconds; AI never runs in the background.

## Technical Analysis Engine — ta-v1.0.0

The dashboard runs local technical analysis without an API key. The observation
uses M15 as primary, H1 context (H4 configurable), and optional M5 timing.
Chart timeframe selection is independent of these roles.

- `GET /api/technical/XAUUSD` — versioned observation.
- `GET /api/technical/XAUUSD?htf=H4&timing=false` — alternate context.
- `engines/technical.py`: pure `analyze(snapshot, config)`, canonical JSON.
- `engines/config.py`: frozen, hashed numerical defaults.
- `engines/indicators.py`: SMA-seeded EMA20/50, rolling-mean ATR14,
  previous-50 ATR baseline, normalized six-close move and efficiency.
- `engines/structure.py`: strict confirmed swings, bounded zones, location and regime.
- `market_data.py`: frozen multi-timeframe inputs, symbol metadata, quotes and schedules.
- `mt5_adapter.py`: resolved MT5 symbol → closed-candle snapshot.
- `replay.py`: causal replay, state duration/flicker report and reference comparison.

See [the implementation and acceptance notes](docs/technical-v1.md) for policies,
configuration, known limitations, and broker verification steps. Numerical
thresholds are provisional; no performance or profitability claim is made.

The former RSI/range-high implementation has been replaced. The optional AI route
now receives the versioned observation and is instructed to explain its facts
without producing trade instructions. Risk and Signal engines remain separate,
unimplemented modules. Quotes/chart fetching and AI HTTP orchestration still
reside in `main.py`; a shared provider/cache is a future integration improvement.

## Limits and safety

The app stops analysis if its last quote is over 120 seconds old. Some markets can be closed or go without ticks, so the timestamp matters. Symbols may differ by account; the app attempts common suffixes and reports missing symbols. Quote delivery and model responses can lag. Never use the analysis as the sole basis for a trade. Keep execution inside MT5 after checking the current bid/ask and your own risk limit.

## Reliability and charting

The chart displays OHLC candlesticks with price/time labels. Hover over a candle for its values; the last candle is forming. Quote ages keep advancing between refreshes. Stale quotes and disconnected feeds are marked, and analysis is disabled until current quotes and candle history are available. Analysis results are labeled with their symbol, timeframe, and quote snapshot time; changing the selection clears them.

For broker-specific names, set `MT5_SYMBOL_XAUUSD`, `MT5_SYMBOL_BTCUSD`, `MT5_SYMBOL_GBPUSD`, or `MT5_SYMBOL_EURUSD` in `.env` to the exact Market Watch name. Automatic matching accepts attached suffixes such as `XAUUSDm`; ambiguous suffix matches require an explicit mapping.

Run backend reliability tests from this directory after installing requirements:

```powershell
python -m unittest discover -s tests -v
```

With Node.js installed, run the frontend request-race and stale-state checks:

```powershell
node --test tests/frontend.test.cjs
```


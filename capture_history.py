"""Read-only export for replay. Never sends orders or exports account credentials."""
import argparse
from dataclasses import asdict, replace
import json
from pathlib import Path
from datetime import datetime, timezone
import main
from engines.config import AnalysisConfig
from mt5_adapter import capture_snapshot
from market_data import Candle, TimeframeData, PERIOD_SECONDS
from broker_time import to_utc, from_utc


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('symbol', choices=main.WATCH)
    parser.add_argument('--output', required=True)
    parser.add_argument('--bars', type=int, default=2000)
    parser.add_argument('--as-of', help='UTC ISO instant, e.g. 2026-09-01T00:00:00+00:00')
    args = parser.parse_args()
    if args.bars < 250 or args.bars > 100000:
        parser.error('--bars must be between 250 and 100000')
    end = datetime.fromisoformat(args.as_of.replace('Z','+00:00')) if args.as_of else datetime.fromtimestamp(main.utc_now(), timezone.utc)
    if end.tzinfo is None:
        parser.error('--as-of must include UTC offset')
    with main.lock:
        main.connect()
        symbol = main.resolve(args.symbol)
        snapshot = capture_snapshot(main.mt5, symbol, end.timestamp(), AnalysisConfig())
        frames = []
        for tf in AnalysisConfig().active_timeframes:
            broker_end = datetime.fromtimestamp(from_utc(end.timestamp()), timezone.utc)
            rates = main.mt5.copy_rates_from(symbol, getattr(main.mt5, 'TIMEFRAME_'+tf), broker_end, args.bars+1)
            candles = () if rates is None else tuple(Candle(int(to_utc(r['time'])),float(r['open']),float(r['high']),float(r['low']),float(r['close']),int(r['tick_volume'])) for r in rates if to_utc(r['time'])+PERIOD_SECONDS[tf] <= end.timestamp())
            frames.append(TimeframeData(tf,candles,'HISTORY_UNAVAILABLE' if rates is None else None))
        snapshot = replace(snapshot,timeframes=tuple(frames),quote=None,connected=None)
    Path(args.output).write_text(json.dumps(asdict(snapshot),allow_nan=False,indent=2),encoding='utf-8')
    print(f'Exported {symbol}: '+', '.join(f'{f.timeframe}={len(f.candles)}' for f in frames))

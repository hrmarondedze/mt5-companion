"""Validate native MT5 CSV exports; produces measured parity and replay reports."""
import argparse
import csv
from collections import defaultdict, Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from market_data import Candle, SymbolMetadata, TimeframeData, MarketSnapshot, utc
from engines.config import AnalysisConfig
from engines.indicators import ema_series, atr_series
from replay import replay


def validate(reference_path, clock_path, metadata_path):
    reference_path = Path(reference_path)
    clock_row = next(csv.DictReader(Path(clock_path).open(encoding='utf-8-sig')))
    offset = int(clock_row['trade_server']) - int(clock_row['gmt'])
    metadata = json.loads(Path(metadata_path).read_text())
    groups = defaultdict(list)
    with reference_path.open(encoding='utf-8-sig') as source:
        for row in csv.DictReader(source):
            groups[row['symbol'], row['timeframe'].removeprefix('PERIOD_')].append(row)
    config = AnalysisConfig()
    histories, comparisons = defaultdict(list), []
    for (symbol, tf), rows in groups.items():
        bars = tuple(Candle(int(r['bar_open_server'])-offset, *(float(r[k]) for k in ('open','high','low','close')), int(r['tick_volume'])) for r in rows)
        if any(a.time >= b.time for a,b in zip(bars,bars[1:])):
            raise ValueError('Invalid reference timestamp order')
        histories[symbol].append(TimeframeData(tf,bars))
        tick = metadata[symbol]['trade_tick_size']
        errors = dict(ema20=0.,ema50=0.,atr14=0.)
        failed, count = 0, 0
        for i in range(config.history_bars-1,len(bars)):
            segment = bars[i-config.history_bars+1:i+1]
            closes = [c.close for c in segment]
            calculated = dict(ema20=ema_series(closes,20)[-1],ema50=ema_series(closes,50)[-1],atr14=atr_series(segment)[-1])
            tolerance = max(2*tick,1e-6*abs(closes[-1]))
            current_errors = {k:abs(v-float(rows[i][k])) for k,v in calculated.items()}
            for k,v in current_errors.items(): errors[k]=max(errors[k],v)
            failed += int(any(v > tolerance for v in current_errors.values()))
            count += 1
        comparisons.append(dict(symbol=symbol,timeframe=tf,checked_bars=count,failed_bars=failed,max_absolute_errors=errors,
                                tolerance_rule='max(2 * trade_tick_size, 1e-6 * abs(close))',trade_tick_size=tick))
    reports = []
    for symbol, frames in histories.items():
        primary = next(f for f in frames if f.timeframe=='M15').candles
        if len(primary)<1500: raise ValueError('Need 1500 M15 bars for separated periods')
        snapshot = MarketSnapshot(symbol,SymbolMetadata(**metadata[symbol]),primary[-1].time+900,tuple(frames))
        for label,start,end in [('earlier',-1000,-751),('later_validation',-250,-1)]:
            start_time,end_time=primary[start].time+900,primary[end].time+900
            measured = replay(snapshot,config,start_time,end_time)
            measured.update(period=label,start_utc=utc(start_time),end_utc=utc(end_time),
                            status_counts=dict(Counter(o['analysis_status'] for o in measured['observations'])))
            reports.append(measured)
            print(f'{symbol} {label}: {measured["causal_checks_passed"]} observations, {measured["transition_count"]} transitions',flush=True)
    return dict(engine_version='ta-v1.0.0',config=asdict(config),config_hash=config.config_hash,
                source_sha256=hashlib.sha256(reference_path.read_bytes()).hexdigest(),source='Native MT5 iMA EMA20/50 PRICE_CLOSE and iATR14 exported by ExportTechnicalReference.mq5',
                terminal_build=int(clock_row['build']),export_clock_utc=utc(int(clock_row['gmt'])),observed_server_offset_seconds=offset,
                time_note='Fixed observed export offset used for these snapshots; no historical DST schedule inferred. Numeric parity is independent of absolute timezone labels.',
                parity=comparisons,replays=reports)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('references');parser.add_argument('clock');parser.add_argument('metadata');parser.add_argument('--output',required=True)
    args=parser.parse_args()
    result=validate(args.references,args.clock,args.metadata)
    Path(args.output).write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf-8')
    print('Native parity failures:',sum(c['failed_bars'] for c in result['parity']))

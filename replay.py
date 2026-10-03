"""Replay saved broker snapshots; no terminal access or execution.

Usage: python replay.py input.json --output report.json
Input uses epoch UTC times and the dataclass field names in market_data.py.
"""
import argparse
from dataclasses import replace
import json
from pathlib import Path
from collections import Counter
from market_data import Candle, SymbolMetadata, MarketSnapshot, TimeframeData, Quote, SessionWindow, PERIOD_SECONDS
from engines.config import AnalysisConfig
from engines.technical import analyze, canonical_json


def load_snapshot(data):
    return MarketSnapshot(data['symbol'], SymbolMetadata(**data['metadata']), data['as_of_utc'],
                          tuple(TimeframeData(f['timeframe'], tuple(Candle(**c) for c in f['candles']), f.get('error_code')) for f in data['timeframes']),
                          Quote(**data['quote']) if data.get('quote') else None, data.get('connected'),
                          tuple(SessionWindow(**s) for s in data.get('sessions', [])))


def replay(snapshot, config=AnalysisConfig(), start_utc=None, end_utc=None):
    primary = next(f for f in snapshot.timeframes if f.timeframe == config.primary)
    states, observations = [], []
    duration = PERIOD_SECONDS[config.primary]
    for bar in primary.candles[config.warmup_bars-1:]:
        as_of = bar.time + duration
        if as_of > snapshot.as_of_utc:
            break
        if start_utc is not None and as_of < start_utc:
            continue
        if end_utc is not None and as_of > end_utc:
            break
        # A lone current quote is not historical tick history. Omit it in both replay variants.
        replay_input = replace(snapshot, as_of_utc=as_of, quote=None, connected=None)
        result = analyze(replay_input, config)
        live_equivalent = replace(replay_input, timeframes=tuple(replace(f, candles=tuple(c for c in f.candles if c.time + PERIOD_SECONDS[f.timeframe] <= as_of)) for f in snapshot.timeframes))
        if canonical_json(result) != canonical_json(analyze(live_equivalent, config)):
            raise AssertionError('Causal replay mismatch')
        states.append(result['primary_regime'])
        observations.append(dict(as_of_utc=result['as_of_utc'], regime=result['primary_regime'], analysis_status=result['analysis_status']))
    runs = []
    for state in states:
        if runs and runs[-1]['regime'] == state:
            runs[-1]['bars'] += 1
        else:
            runs.append(dict(regime=state, bars=1))
    for run in runs:
        run['duration_seconds'] = run['bars'] * duration
    # Boundary runs are censored and cannot be identified as genuine one-bar flickers.
    interior = runs[1:-1]
    return dict(symbol=snapshot.symbol, engine_version='ta-v1.0.0', config_hash=config.config_hash,
                observations=observations, state_counts=dict(Counter(states)), transition_count=max(0, len(runs)-1),
                runs=runs, one_bar_flicker_rate=sum(r['bars'] == 1 for r in interior)/len(interior) if interior else None,
                flicker_denominator='completed interior runs', causal_checks_passed=len(states),
                note='Descriptive stability only; no trading expectancy claim. Separate later validation periods from threshold development.')


def compare_indicators(snapshot, references, config=AnalysisConfig()):
    """References: tf/as_of_utc/ema20/ema50/atr14/indicator_name; export from named MT5 indicators."""
    checks = []
    for row in references:
        if not row.get('indicator_name'):
            raise ValueError('Name the MT5 indicator/configuration used for comparison')
        result = analyze(replace(snapshot, as_of_utc=row['as_of_utc'], quote=None), config)['timeframes'][row['timeframe']]
        if result['status'] == 'unavailable':
            checks.append(dict(status='unavailable', reasons=result['reasons']))
            continue
        tolerance = max(2 * snapshot.metadata.trade_tick_size, 1e-6 * abs(result['last_close']))
        values = dict(ema20=result['trend']['ema20'], ema50=result['trend']['ema50'], atr14=result['volatility']['atr14'])
        checks.append(dict(indicator_name=row['indicator_name'], timeframe=row['timeframe'], as_of_utc=row['as_of_utc'], tolerance=tolerance,
                           errors={k: abs(v-row[k]) for k,v in values.items()}, passed=all(abs(v-row[k]) <= tolerance for k,v in values.items())))
    return checks


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('input')
    parser.add_argument('--output', required=True)
    parser.add_argument('--config')
    parser.add_argument('--references')
    args = parser.parse_args()
    config = AnalysisConfig(**json.loads(Path(args.config).read_text())) if args.config else AnalysisConfig()
    snapshot = load_snapshot(json.loads(Path(args.input).read_text()))
    report = replay(snapshot, config)
    if args.references:
        report['indicator_comparison'] = compare_indicators(snapshot, json.loads(Path(args.references).read_text()), config)
    Path(args.output).write_text(canonical_json(report), encoding='utf-8')

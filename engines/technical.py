"""ta-v1.0.0 pure analysis. No clock, network, terminal, or order access."""
from dataclasses import asdict
import json
import math
from market_data import PERIOD_SECONDS, candle_error, utc
from engines.config import AnalysisConfig
from engines.indicators import readings
from engines.structure import structure, location, regime

EngineResult = dict


def canonical_json(result):
    return json.dumps(result, sort_keys=True, separators=(',', ':'), allow_nan=False)


def unavailable(code):
    return dict(status='unavailable', last_bar_open_utc=None, last_bar_close_utc=None,
                trend=None, structure=None, volatility=None, momentum=None, location=None,
                reasons=[{'code': code}])


def quality(bars, snapshot, duration, config):
    reasons, status = [], 'valid'
    missing, unexplained = 0, 0
    # Classify missing expected bar opens, including the trailing interval, only with a supplied schedule.
    intervals = [(a.time, max(0, math.ceil((b.time-a.time)/duration)-1)) for a,b in zip(bars,bars[1:])]
    intervals.append((bars[-1].time, max(0, math.floor((snapshot.as_of_utc-bars[-1].time-duration)/duration))))
    for start, count in intervals:
        if not count:
            continue
        missing += count
        if snapshot.sessions:
            run = 0
            for index in range(1, count + 1):
                opened = any(s.contains(start + index * duration) for s in snapshot.sessions)
                run = run + 1 if opened else 0
                unexplained += int(opened)
                if run >= config.gap_unavailable_bars:
                    status = 'unavailable'
    if unexplained:
        if status != 'unavailable':
            status = 'degraded'
        reasons.append({'code': 'OPEN_SESSION_GAP', 'missing_bars': unexplained})
    elif missing:
        reasons.append({'code': 'EXPECTED_SESSION_GAP' if snapshot.sessions else 'GAP_SCHEDULE_UNKNOWN', 'missing_bars': missing})
        if not snapshot.sessions:
            status = 'degraded'
    age = snapshot.as_of_utc - (bars[-1].time + duration)
    if age > duration + config.history_grace_seconds:
        reasons.append({'code': 'OLD_LAST_CLOSED_BAR', 'age_seconds': age})
    return status, reasons


def timeframe_result(data, snapshot, config):
    if data is None or data.error_code:
        return unavailable(data.error_code if data else 'MISSING_TIMEFRAME')
    error = candle_error(data.candles)
    if error:
        return unavailable(error)
    duration = PERIOD_SECONDS[data.timeframe]
    bars = tuple(b for b in data.candles if b.time + duration <= snapshot.as_of_utc)[-config.history_bars:]
    if len(bars) < config.warmup_bars:
        return unavailable('INSUFFICIENT_WARMUP')
    status, reasons = quality(bars, snapshot, duration, config)
    if status == 'unavailable':
        result = unavailable('OPEN_SESSION_GAP')
        result['reasons'] = reasons
        return result
    try:
        trend, volatility, momentum, atrs = readings(bars, config)
    except ValueError as exc:
        return unavailable(str(exc))
    current_structure = structure(bars, atrs, duration, snapshot.metadata.trade_tick_size, config)
    prior_structure = structure(bars[:-1], atrs[:-1], duration, snapshot.metadata.trade_tick_size, config)
    state, breakout, code = regime(bars, trend, current_structure, volatility, prior_structure['zones'], config)
    return dict(status=status, last_bar_open_utc=utc(bars[-1].time), last_bar_close_utc=utc(bars[-1].time + duration),
                history_start_utc=utc(bars[0].time), closed_bar_count=len(bars), last_close=bars[-1].close,
                trend=trend, structure=current_structure, volatility=volatility, momentum=momentum,
                location=location(bars[-1].close, current_structure['zones'], volatility['atr14'], config.near_atr),
                regime=state, breakout=breakout, reasons=reasons + [{'code': code}])


def quote_context(snapshot, primary, config):
    q = snapshot.quote
    session = '+'.join(sorted(s.label for s in snapshot.sessions if s.contains(snapshot.as_of_utc))) if snapshot.sessions else 'unknown'
    context = dict(quote_time_utc=None, quote_age_seconds=None, bid=None, ask=None, spread_price=None,
                   spread_points=None, spread_atr_ratio=None, session=session or 'closed', live_location=None, reasons=[])
    if snapshot.connected is False:
        status, code = 'disconnected', 'FEED_DISCONNECTED'
    elif q is None:
        status, code = 'unknown', 'QUOTE_MISSING'
    elif not all(math.isfinite(v) for v in (q.time, q.bid, q.ask)) or q.time <= 0 or q.bid <= 0 or q.ask < q.bid:
        status, code = 'unknown', 'INVALID_QUOTE'
    elif q.time > snapshot.as_of_utc:
        status, code = 'unknown', 'QUOTE_AFTER_AS_OF'
    else:
        context.update(quote_time_utc=utc(q.time), quote_age_seconds=snapshot.as_of_utc - q.time)
        if snapshot.sessions and not session:
            status, code = 'closed', 'KNOWN_SESSION_CLOSED'
        elif snapshot.as_of_utc - q.time > config.quote_max_age_seconds:
            status, code = 'stale', 'QUOTE_STALE'
        else:
            status, code = 'fresh', 'QUOTE_FRESH'
            spread = q.ask - q.bid
            context.update(bid=q.bid, ask=q.ask, spread_price=spread, spread_points=spread / snapshot.metadata.point)
            if primary['status'] != 'unavailable':
                atr = primary['volatility']['atr14']
                context.update(spread_atr_ratio=spread / atr,
                               live_location={side: location(getattr(q, side), primary['structure']['zones'], atr, config.near_atr) for side in ('bid', 'ask')})
            else:
                context['reasons'].append({'code': 'PRIMARY_UNAVAILABLE_FOR_LIVE_CONTEXT'})
    context['reasons'].append({'code': code})
    return status, context


def analyze(snapshot, config=AnalysisConfig()) -> EngineResult:
    if not math.isfinite(snapshot.as_of_utc) or snapshot.as_of_utc <= 0:
        raise ValueError('INVALID_AS_OF')
    meta = snapshot.metadata
    metadata_ok = all(math.isfinite(v) and v > 0 for v in (meta.point, meta.trade_tick_size)) and isinstance(meta.digits, int) and 0 <= meta.digits <= 12
    duplicates = len({t.timeframe for t in snapshot.timeframes}) != len(snapshot.timeframes)
    timeframes = {tf: (unavailable('INVALID_SYMBOL_METADATA') if not metadata_ok else unavailable('DUPLICATE_TIMEFRAME') if duplicates
                      else timeframe_result(next((t for t in snapshot.timeframes if t.timeframe == tf), None), snapshot, config)) for tf in config.active_timeframes}
    primary, higher = timeframes[config.primary], timeframes[config.htf]
    alignment = 'unavailable'
    if primary['trend'] and higher['trend']:
        p, h = primary['trend']['state'], higher['trend']['state']
        alignment = 'mixed' if 'flat_mixed' in (p, h) else 'aligned' if p == h else 'opposed'
    if metadata_ok:
        feed, context = quote_context(snapshot, primary, config)
    else:
        feed, context = 'unknown', dict(quote_time_utc=None, quote_age_seconds=None, bid=None, ask=None, spread_price=None,
                                       spread_points=None, spread_atr_ratio=None, session='unknown', live_location=None,
                                       reasons=[{'code': 'INVALID_SYMBOL_METADATA'}])
    result = dict(schema_version='1.0', engine_version='ta-v1.0.0', config_id=config.config_id, config_hash=config.config_hash,
                  config=asdict(config), symbol=snapshot.symbol, symbol_metadata=asdict(meta) if metadata_ok else None,
                  as_of_utc=utc(snapshot.as_of_utc), primary_timeframe=config.primary, analysis_status=primary['status'],
                  live_feed_status=feed, primary_regime=primary.get('regime', 'unavailable'), timeframes=timeframes,
                  market_context=context, htf_alignment=alignment, htf_bias=higher['trend']['state'] if higher['trend'] else None,
                  timing_momentum=timeframes[config.timing]['momentum'] if config.timing else None,
                  reasons=primary['reasons'] + [{'code': 'HTF_' + alignment.upper()}] + context['reasons'])
    # Fail closed on arithmetic overflow as well as NaN; JSON never contains fabricated values.
    try:
        canonical_json(result)
    except ValueError:
        raise ValueError('NONFINITE_CALCULATION') from None
    return result


analyze_technical = analyze

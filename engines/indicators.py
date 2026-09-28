"""Full-length indicator series: unavailable warmup elements are None."""
from statistics import median


def ema_series(values, period):
    out = [None] * len(values)
    if len(values) < period:
        return out
    out[period - 1] = sum(values[:period]) / period
    for i in range(period, len(values)):
        out[i] = out[i - 1] + 2 / (period + 1) * (values[i] - out[i - 1])
    return out


def atr_series(bars, period=14):
    tr = [None] + [max(b.high - b.low, abs(b.high - a.close), abs(b.low - a.close))
                   for a, b in zip(bars, bars[1:])]
    return [None if i < period else sum(tr[i-period+1:i+1]) / period for i in range(len(bars))]


def readings(bars, config):
    closes = [b.close for b in bars]
    atrs = atr_series(bars)
    atr = atrs[-1]
    if atr is None or atr <= 0:
        raise ValueError('NONPOSITIVE_ATR')
    baseline = median(atrs[-51:-1])
    if baseline <= 0:
        raise ValueError('NONPOSITIVE_ATR_BASELINE')
    fast, slow = ema_series(closes, 20), ema_series(closes, 50)
    separation, slope = (fast[-1] - slow[-1]) / atr, (slow[-1] - slow[-11]) / atr
    state = ('up' if separation > config.separation_deadband and slope > config.slope_deadband and closes[-1] > slow[-1]
             else 'down' if separation < -config.separation_deadband and slope < -config.slope_deadband and closes[-1] < slow[-1]
             else 'flat_mixed')
    trend = dict(state=state, ema20=fast[-1], ema50=slow[-1], ema_separation_atr=separation,
                 ema50_slope_atr=slope, close_relative_to_ema50='above' if closes[-1] > slow[-1] else 'below' if closes[-1] < slow[-1] else 'equal',
                 reasons=[{'code': 'TREND_' + state.upper()}])
    relative = atr / baseline
    volatility = dict(atr14=atr, smoothing='SMA_TR_14', baseline_atr=baseline, relative_atr=relative,
                      state='quiet' if relative < config.quiet_threshold else 'elevated' if relative > config.elevated_threshold else 'normal')
    changes = [abs(b - a) for a, b in zip(closes[-6:-1], closes[-5:])]
    path, net = sum(changes), closes[-1] - closes[-6]
    efficiency = min(1., max(0., abs(net) / path)) if path else 0.
    move = net / atr
    direction = 'upward' if move > 0 else 'downward'
    momentum = dict(normalized_move=move, efficiency=efficiency, path=path, no_movement=path == 0,
                    single_bar_spike=bool(path and max(changes) / path >= config.spike_share and max(changes) >= config.spike_atr * atr),
                    state='choppy' if abs(move) < config.momentum_move else direction + ('_strong' if efficiency >= config.momentum_efficiency else '_weak'))
    return trend, volatility, momentum, atrs

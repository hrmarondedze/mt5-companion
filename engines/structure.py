"""Causal swings and deterministic, same-side, bounded zone clustering."""
from market_data import utc


def confirmed_swings(bars, atrs, duration, radius):
    swings = []
    for i in range(radius, len(bars) - radius):
        neighbors = bars[i-radius:i] + bars[i+1:i+radius+1]
        for kind in ('high', 'low'):
            value = getattr(bars[i], kind)
            if all(value > getattr(b, kind) if kind == 'high' else value < getattr(b, kind) for b in neighbors):
                confirmation = i + radius
                swings.append(dict(id=f'{kind}:{bars[i].time}', kind=kind, price=value,
                                   occurred_at_utc=utc(bars[i].time), confirmed_at_utc=utc(bars[confirmation].time + duration),
                                   occurrence_index=i, confirmation_index=confirmation,
                                   atr_at_confirmation=atrs[confirmation]))
    return swings


def zones_from_swings(swings, bar_count, tick_size, config):
    zones = []
    for swing in swings:
        atr = swing['atr_at_confirmation']
        if swing['occurrence_index'] < bar_count - config.zone_lookback or atr is None or atr <= 0:
            continue
        half = max(config.zone_half_atr * atr, config.zone_min_ticks * tick_size)
        candidate = dict(id=swing['id'], kind='resistance' if swing['kind'] == 'high' else 'support',
                         lower=swing['price'] - half, upper=swing['price'] + half,
                         source_swing_ids=[swing['id']], active_from_utc=swing['confirmed_at_utc'],
                         max_width=max(config.zone_max_width_atr * atr, 2 * config.zone_min_ticks * tick_size))
        # Oldest-first merge, union bounds, strictest source cap. Refused merges stay separate.
        for zone in list(zones):
            lower, upper = min(zone['lower'], candidate['lower']), max(zone['upper'], candidate['upper'])
            cap = min(zone['max_width'], candidate['max_width'])
            if zone['kind'] == candidate['kind'] and zone['lower'] <= candidate['upper'] and candidate['lower'] <= zone['upper'] and upper - lower <= cap:
                candidate.update(lower=lower, upper=upper, max_width=cap,
                                 source_swing_ids=zone['source_swing_ids'] + candidate['source_swing_ids'],
                                 id=zone['id'] + '+' + candidate['id'])
                zones.remove(zone)
        zones.append(candidate)
    return sorted(zones, key=lambda z: (z['kind'], z['lower'], z['id']))


def structure(bars, atrs, duration, tick_size, config):
    swings = confirmed_swings(bars, atrs, duration, config.swing_radius)
    highs = [s for s in swings if s['kind'] == 'high'][-2:]
    lows = [s for s in swings if s['kind'] == 'low'][-2:]
    hc = None if len(highs) < 2 else 'higher' if highs[-1]['price'] > highs[-2]['price'] else 'lower' if highs[-1]['price'] < highs[-2]['price'] else 'equal'
    lc = None if len(lows) < 2 else 'higher' if lows[-1]['price'] > lows[-2]['price'] else 'lower' if lows[-1]['price'] < lows[-2]['price'] else 'equal'
    state = 'insufficient_swings' if hc is None or lc is None else 'rising' if hc == lc == 'higher' else 'falling' if hc == lc == 'lower' else 'mixed'
    return dict(state=state, high_comparison=hc, low_comparison=lc, last_two_highs=highs, last_two_lows=lows,
                swings=swings, zones=zones_from_swings(swings, len(bars), tick_size, config),
                reasons=[{'code': 'STRUCTURE_' + state.upper()}])


def location(price, zones, atr, near):
    def nearest(kind):
        options = []
        for zone in zones:
            if zone['kind'] != kind:
                continue
            signed = price - zone['upper'] if price > zone['upper'] else price - zone['lower'] if price < zone['lower'] else 0.
            options.append(dict(zone=zone, signed_distance_price=signed, distance_price=abs(signed),
                                signed_distance_atr=signed / atr, distance_atr=abs(signed) / atr))
        return min(options, key=lambda x: (x['distance_price'], x['zone']['id'])) if options else None
    support, resistance = nearest('support'), nearest('resistance')
    choices = [x for x in (support, resistance) if x is not None]
    closest = min(choices, key=lambda x: (x['distance_price'], x['zone']['kind'])) if choices else None
    state = 'no_zones'
    if closest:
        state = ('inside_' if closest['distance_price'] == 0 else 'near_') + closest['zone']['kind'] if closest['distance_atr'] <= near else 'between_zones'
    return dict(state=state, reference_price=price, nearest_support=support, nearest_resistance=resistance,
                reasons=[{'code': 'LOCATION_' + state.upper()}])


def regime(bars, trend, structure_now, volatility, prior_zones, config):
    previous, current = bars[-2].close, bars[-1].close
    buffer = config.breakout_buffer_atr * volatility['atr14']
    active_break = False
    for zone in prior_zones:
        if zone['lower'] <= previous <= zone['upper']:
            direction = 'up' if current > zone['upper'] + buffer else 'down' if current < zone['lower'] - buffer else None
            active_break = active_break or direction is not None
            if direction and volatility['state'] == 'elevated':
                return 'breakout_candidate', dict(direction=direction, source_zone=zone), 'ACTIVE_ZONE_BREAK_WITH_ELEVATED_VOLATILITY'
    if trend['state'] == 'up' and structure_now['state'] == 'rising':
        return 'trending_up', None, 'TREND_STRUCTURE_ALIGNED_UP'
    if trend['state'] == 'down' and structure_now['state'] == 'falling':
        return 'trending_down', None, 'TREND_STRUCTURE_ALIGNED_DOWN'
    supports = [z for z in structure_now['zones'] if z['kind'] == 'support' and len(z['source_swing_ids']) >= 2]
    resistances = [z for z in structure_now['zones'] if z['kind'] == 'resistance' and len(z['source_swing_ids']) >= 2]
    if trend['state'] == 'flat_mixed' and not active_break:
        for support in supports:
            for resistance in resistances:
                if support['upper'] < resistance['lower'] and support['lower'] <= current <= resistance['upper']:
                    return 'range', None, 'BOUNDED_REPEATED_TOUCHES'
    return 'mixed', None, 'NO_REGIME_CONFLUENCE'

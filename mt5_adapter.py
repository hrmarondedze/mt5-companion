"""Read one broker snapshot under the caller's terminal lock."""
from market_data import Candle, MarketSnapshot, SymbolMetadata, Quote, TimeframeData, PERIOD_SECONDS
from broker_time import to_utc


def capture_snapshot(mt5, symbol, as_of, config):
    info = mt5.symbol_info(symbol)
    metadata = SymbolMetadata(float(info.point), float(info.trade_tick_size), int(info.digits)) if info else SymbolMetadata(0, 0, -1)
    frames = []
    for tf in config.active_timeframes:
        rates = mt5.copy_rates_from_pos(symbol, getattr(mt5, 'TIMEFRAME_' + tf), 0, config.history_bars + 1)
        if rates is None:
            frames.append(TimeframeData(tf, (), 'HISTORY_UNAVAILABLE'))
            continue
        try:
            all_bars = tuple(Candle(int(to_utc(r['time'])), float(r['open']), float(r['high']), float(r['low']),
                                    float(r['close']), int(r['tick_volume'])) for r in rates)
            # Reject disorder, not silently repair it; sorted MT5 output is the contract.
            from market_data import candle_error
            error = candle_error(all_bars)
            closed = tuple(b for b in all_bars if b.time + PERIOD_SECONDS[tf] <= as_of)
            frames.append(TimeframeData(tf, closed, error))
        except (ValueError, TypeError, KeyError, OverflowError):
            frames.append(TimeframeData(tf, (), 'INVALID_BROKER_BARS'))
    tick = mt5.symbol_info_tick(symbol)
    quote = None
    if tick is not None:
        stamp = tick.time_msc / 1000 if tick.time_msc else tick.time
        quote = Quote(to_utc(stamp), float(tick.bid), float(tick.ask))
    # No broker schedule is guessed. A successful historical read does not prove live connectivity.
    terminal = mt5.terminal_info()
    connected = bool(terminal.connected) if terminal is not None else None
    return MarketSnapshot(symbol, metadata, as_of, tuple(frames), quote, connected)

"""Frozen broker-neutral inputs. Times are UTC Unix seconds internally."""
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import math

PERIOD_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600, "H4": 14400}


def utc(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat().replace('+00:00', 'Z')


@dataclass(frozen=True)
class Candle:
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: int = 0


@dataclass(frozen=True)
class SymbolMetadata:
    point: float
    trade_tick_size: float
    digits: int


@dataclass(frozen=True)
class Quote:
    time: float
    bid: float
    ask: float


@dataclass(frozen=True)
class SessionWindow:
    """Explicit broker schedule in an IANA zone; weekdays refer to opening day."""
    label: str
    timezone: str
    weekdays: tuple[int, ...]
    open_minute: int
    close_minute: int

    def __post_init__(self):
        ZoneInfo(self.timezone)
        if not 0 <= self.open_minute < 1440 or not 0 <= self.close_minute <= 1440 or any(d not in range(7) for d in self.weekdays):
            raise ValueError('INVALID_SESSION_SCHEDULE')

    def contains(self, timestamp):
        local = datetime.fromtimestamp(timestamp, ZoneInfo(self.timezone))
        minute = local.hour * 60 + local.minute
        if self.open_minute < self.close_minute:
            return local.weekday() in self.weekdays and self.open_minute <= minute < self.close_minute
        day = local.weekday() if minute >= self.open_minute else (local.weekday() - 1) % 7
        return day in self.weekdays and (minute >= self.open_minute or minute < self.close_minute)


@dataclass(frozen=True)
class TimeframeData:
    timeframe: str
    candles: tuple[Candle, ...]
    error_code: str | None = None


@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    metadata: SymbolMetadata
    as_of_utc: float
    timeframes: tuple[TimeframeData, ...]
    quote: Quote | None = None
    connected: bool | None = None
    sessions: tuple[SessionWindow, ...] = ()


def candle_error(bars):
    if any(a.time >= b.time for a, b in zip(bars, bars[1:])):
        return 'NON_MONOTONIC_TIMESTAMPS'
    for c in bars:
        if not math.isfinite(c.time) or c.time <= 0:
            return 'INVALID_TIMESTAMP'
        if not all(math.isfinite(v) for v in (c.open, c.high, c.low, c.close)):
            return 'NONFINITE_PRICE'
        if c.high < max(c.open, c.close, c.low) or c.low > min(c.open, c.close, c.high):
            return 'INVALID_OHLC'
    return None

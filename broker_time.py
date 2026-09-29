"""Explicit broker wall-time interpretation; never infer offsets from stale ticks."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import os


def broker_timezone():
    return os.getenv('MT5_TIMESTAMP_TIMEZONE', 'UTC')


def to_utc(stamp):
    zone = ZoneInfo(broker_timezone())
    wall = datetime.fromtimestamp(stamp, timezone.utc).replace(tzinfo=None)
    # A repeated local time cannot be resolved causally from a timestamp alone.
    first, second = wall.replace(tzinfo=zone, fold=0), wall.replace(tzinfo=zone, fold=1)
    if first.utcoffset() != second.utcoffset():
        raise ValueError('AMBIGUOUS_BROKER_TIMESTAMP')
    return first.timestamp()


def from_utc(stamp):
    local = datetime.fromtimestamp(stamp, ZoneInfo(broker_timezone()))
    return local.replace(tzinfo=timezone.utc).timestamp()

import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
from datetime import datetime, timezone
from broker_time import to_utc, from_utc
from utc_clock import UTCClock
from mt5_adapter import capture_snapshot
from engines.config import AnalysisConfig


class TimeTests(unittest.TestCase):
    def test_explicit_broker_offset_roundtrip(self):
        with patch.dict('os.environ', {'MT5_TIMESTAMP_TIMEZONE':'Etc/GMT-3'}):
            self.assertEqual(to_utc(1790674523),1790663723)
            self.assertEqual(from_utc(1790663723),1790674523)

    def test_dst_ambiguity_rejected(self):
        wall=datetime(2026,11,1,1,30,tzinfo=timezone.utc).timestamp()
        with patch.dict('os.environ', {'MT5_TIMESTAMP_TIMEZONE':'America/New_York'}):
            with self.assertRaisesRegex(ValueError,'AMBIGUOUS'):
                to_utc(wall)

    def test_clock_uses_https_then_monotonic_without_pc_time(self):
        response=Mock()
        response.__enter__=Mock(return_value=response)
        response.__exit__=Mock(return_value=False)
        response.headers={'Date':'Mon, 28 Sep 2026 23:30:27 GMT'}
        with patch('utc_clock.urllib.request.urlopen',return_value=response) as get, patch('utc_clock.time.monotonic',return_value=100),patch('utc_clock.time.time',side_effect=AssertionError('PC wall clock used')):
            clock=UTCClock()
            before=clock.now()
            self.assertEqual(get.call_count,2)
            with patch('utc_clock.time.monotonic',return_value=110):
                self.assertEqual(clock.now(),before+10)
            self.assertEqual(get.call_count,2)

    def test_clock_fails_closed_and_throttles_retries(self):
        with patch('utc_clock.urllib.request.urlopen',side_effect=OSError('offline')) as get,patch('utc_clock.time.monotonic',return_value=100):
            clock=UTCClock()
            for _ in range(2):
                with self.assertRaisesRegex(RuntimeError,'UTC_CLOCK_UNAVAILABLE'): clock.now()
            self.assertEqual(get.call_count,2)

    def test_clock_expires_without_consensus(self):
        clock=UTCClock();clock._epoch=1000;clock._anchor=100
        with patch('utc_clock.urllib.request.urlopen',side_effect=OSError('offline')),patch('utc_clock.time.monotonic',return_value=1001):
            with self.assertRaises(RuntimeError):clock.now()

    def test_future_latest_tick_replaced_by_actual_historical_tick(self):
        mt=Mock()
        mt.symbol_info.return_value=SimpleNamespace(point=.01,trade_tick_size=.01,digits=2)
        mt.copy_rates_from_pos.return_value=[]
        mt.symbol_info_tick.return_value=SimpleNamespace(time_msc=2001000,bid=100,ask=101)
        mt.copy_ticks_range.return_value=[dict(time=1999,time_msc=1999500,bid=99,ask=100),dict(time=2001,time_msc=2001000,bid=100,ask=101)]
        with patch.dict('os.environ', {'MT5_TIMESTAMP_TIMEZONE':'UTC'}):
            result=capture_snapshot(mt,'XAUUSD',2000,AnalysisConfig())
        self.assertEqual(result.quote.time,1999.5)
        self.assertEqual(result.quote.bid,99)

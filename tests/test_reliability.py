import os
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
import main

class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'OPENAI_API_KEY':'test'}, clear=True)
        self.env.start()
        self.mt5 = Mock()
        self.mt5.initialize.return_value = True
        self.mt5.symbol_select.return_value = True
        self.mt5.symbols_get.return_value = [SimpleNamespace(name=n) for n in main.WATCH]
        self.mt5.symbol_info_tick.return_value = SimpleNamespace(bid=100., ask=101., time_msc=int(time.time()*1000))
        self.bridge = patch.object(main, 'mt5', self.mt5)
        self.bridge.start()
    def tearDown(self):
        self.bridge.stop()
        self.env.stop()
    def test_exact_symbol_preferred(self):
        self.mt5.symbols_get.return_value = [SimpleNamespace(name=n) for n in ['XAUUSDm','XAUUSD']]
        self.assertEqual(main.resolve('XAUUSD'), 'XAUUSD')
    def test_attached_suffix(self):
        self.mt5.symbols_get.return_value = [SimpleNamespace(name='XAUUSDm')]
        self.assertEqual(main.resolve('XAUUSD'), 'XAUUSDm')
    def test_ambiguous_suffix_requires_mapping(self):
        self.mt5.symbols_get.return_value = [SimpleNamespace(name=n) for n in ['XAUUSDm','XAUUSD.pro']]
        with self.assertRaises(main.HTTPException) as exc: main.resolve('XAUUSD')
        self.assertEqual(exc.exception.status_code,409)
    def test_override(self):
        os.environ['MT5_SYMBOL_XAUUSD'] = 'GOLD'
        self.assertEqual(main.resolve('XAUUSD'),'GOLD')
    def test_missing_symbol(self):
        self.mt5.symbols_get.return_value = []
        with self.assertRaises(main.HTTPException): main.resolve('XAUUSD')
    def test_disconnect(self):
        self.mt5.initialize.return_value = False
        with self.assertRaises(main.HTTPException) as exc: main.market()
        self.assertEqual(exc.exception.status_code,503)
    def test_invalid_quote(self):
        self.mt5.symbol_info_tick.return_value.bid = float('nan')
        self.assertTrue(main.market()['symbols'][0]['error'])
    def test_missing_history(self):
        self.mt5.copy_rates_from_pos.return_value = []
        with self.assertRaises(main.HTTPException): main.candles('XAUUSD')
    def test_stale_quote_blocks_analysis(self):
        self.mt5.symbol_info_tick.return_value.time_msc = int((time.time()-180)*1000)
        with patch.object(main,'candles',return_value={'timeframe':'M5','candles':[{'time':time.time()}]}):
            with self.assertRaises(main.HTTPException) as exc: main.analyze(main.AnalysisRequest(symbol='XAUUSD'))
        self.assertIn('Quote',exc.exception.detail)
    def test_stale_candles_block_analysis(self):
        with patch.object(main,'candles',return_value={'timeframe':'M5','candles':[{'time':time.time()-1000}]}):
            with self.assertRaises(main.HTTPException) as exc: main.analyze(main.AnalysisRequest(symbol='XAUUSD'))
        self.assertIn('history is stale',exc.exception.detail)

if __name__ == '__main__': unittest.main()

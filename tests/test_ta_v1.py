import math
import unittest
from dataclasses import replace
from unittest.mock import Mock, patch
from datetime import datetime, timezone
from types import SimpleNamespace

import main
from market_data import Candle, MarketSnapshot, SymbolMetadata, Quote, TimeframeData, SessionWindow
from engines.config import AnalysisConfig
from engines.indicators import ema_series, atr_series, readings
from engines.structure import confirmed_swings, zones_from_swings, regime, location
from engines.technical import analyze, canonical_json
from mt5_adapter import capture_snapshot
from replay import replay

CFG = AnalysisConfig()
META = SymbolMetadata(.01, .01, 2)
START = 1700000100


def bars(count=300, duration=900, flat=False):
    return tuple(Candle(START+i*duration, 100 if flat else 100+i*.1+math.sin(i/3),
                        (100 if flat else 100+i*.1+math.sin(i/3))+1,
                        (100 if flat else 100+i*.1+math.sin(i/3))-1,
                        100 if flat else 100+i*.1+math.sin(i/3)) for i in range(count))


def snap(primary=None):
    primary = bars() if primary is None else primary
    as_of = primary[-1].time+900
    higher = tuple(replace(b, time=int(as_of-(300-i)*3600)) for i,b in enumerate(bars()))
    timing = tuple(replace(b, time=int(as_of-(300-i)*300)) for i,b in enumerate(bars()))
    return MarketSnapshot('XAUUSDm', META, as_of, (TimeframeData('M15',primary),TimeframeData('H1',higher),TimeframeData('M5',timing)), Quote(as_of,130,130.02), True)


class FormulaTests(unittest.TestCase):
    def test_ema_sma_seed_and_recurrence(self):
        self.assertEqual(ema_series([1,2,3,4,5],3), [None,None,2,3,4])

    def test_atr_is_rolling_not_wilder(self):
        b = list(bars(70, flat=True))
        b[-1] = replace(b[-1], high=115)
        self.assertEqual(atr_series(b)[-1], 3)
        self.assertEqual(readings(b, CFG)[1]['baseline_atr'], 2)
        self.assertEqual(readings(b, CFG)[1]['state'], 'elevated')

    def test_flat_path_and_positive_atr(self):
        r = analyze(snap(bars(flat=True)))['timeframes']['M15']
        self.assertTrue(r['momentum']['no_movement'])
        self.assertEqual(r['momentum']['efficiency'], 0)
        self.assertEqual(r['trend']['state'], 'flat_mixed')
        self.assertEqual(r['regime'], 'mixed')

    def test_nonpositive_atr_rejected(self):
        b = tuple(replace(c,high=100,low=100) for c in bars(flat=True))
        r = analyze(snap(b))
        self.assertEqual(r['primary_regime'], 'unavailable')
        self.assertEqual(r['reasons'][0]['code'], 'NONPOSITIVE_ATR')

    def test_spike_and_signed_momentum(self):
        b = list(bars(flat=True)); b[-1] = replace(b[-1],close=104,high=105)
        m = analyze(snap(tuple(b)))['timeframes']['M15']['momentum']
        self.assertTrue(m['single_bar_spike'])
        self.assertEqual(m['efficiency'],1)
        self.assertEqual(m['state'],'upward_strong')

    def test_trend_deadband(self):
        r = analyze(snap(),replace(CFG,separation_deadband=100))
        self.assertEqual(r['timeframes']['M15']['trend']['state'],'flat_mixed')

    def test_volatility_boundary_values_are_normal(self):
        b=list(bars(flat=True))
        # Baseline remains 2 because 37 of the previous 50 ATRs are unchanged.
        for factor in (.8, 1.3):
            changed=b[:-14]+[replace(c,high=100+factor,low=100-factor) for c in b[-14:]]
            v=readings(changed,CFG)[1]
            self.assertAlmostEqual(v['relative_atr'],factor)
            # Use the calculated exact ratio as boundary to avoid decimal float representation ambiguity.
            cfg=replace(CFG,quiet_threshold=v['relative_atr']) if factor == .8 else replace(CFG,elevated_threshold=v['relative_atr'])
            self.assertEqual(readings(changed,cfg)[1]['state'],'normal')


class CausalityTests(unittest.TestCase):
    def test_deterministic_canonical_json(self):
        s=snap()
        self.assertEqual(canonical_json(analyze(s)),canonical_json(analyze(s)))

    def test_future_and_forming_bars_do_not_change_result(self):
        s=snap()
        future=replace(s,timeframes=tuple(replace(f,candles=f.candles+(replace(f.candles[-1],time=int(s.as_of_utc),close=999,high=1000),)) for f in s.timeframes))
        self.assertEqual(canonical_json(analyze(s)),canonical_json(analyze(future)))

    def test_timeframe_boundary_keeps_historical_last_bar(self):
        s=snap(); before=analyze(replace(s,as_of_utc=s.as_of_utc-1))
        now=analyze(s)
        self.assertNotEqual(before['timeframes']['H1']['last_bar_close_utc'],now['timeframes']['H1']['last_bar_close_utc'])
        self.assertEqual(now['timeframes']['M15']['closed_bar_count'],300)

    def test_forming_bar_not_counted_as_missing_before_close(self):
        s=snap()
        result=analyze(replace(s,as_of_utc=s.as_of_utc+899.9))
        self.assertEqual(result['timeframes']['M15']['status'],'valid')

    def test_manual_swing_confirmation_and_equal_high(self):
        b=tuple(Candle(1000+i*60,5,h,0,5) for i,h in enumerate([6,7,10,7,6]))
        self.assertEqual(confirmed_swings(b[:-1],[2]*4,60,2),[])
        swings=confirmed_swings(b,[2]*5,60,2)
        self.assertEqual([(s['kind'],s['price']) for s in swings],[('high',10)])
        self.assertEqual(swings[0]['confirmation_index'],4)
        self.assertEqual(confirmed_swings(b[:3]+(replace(b[3],high=10),)+b[4:],[2]*5,60,2),[])

    def test_optional_missing_does_not_invalidate_primary(self):
        s=snap(); r=analyze(replace(s,timeframes=s.timeframes[:2]))
        self.assertEqual(r['analysis_status'],'valid')
        self.assertEqual(r['timeframes']['M5']['status'],'unavailable')

    def test_primary_missing(self):
        s=snap(); r=analyze(replace(s,timeframes=s.timeframes[1:]))
        self.assertEqual(r['primary_regime'],'unavailable')

    def test_replay_equivalence(self):
        report=replay(snap(bars(255)))
        self.assertEqual(report['causal_checks_passed'],6)


class QualityTests(unittest.TestCase):
    def test_bad_metadata(self):
        r=analyze(replace(snap(),metadata=replace(META,trade_tick_size=0)))
        self.assertEqual(r['reasons'][0]['code'],'INVALID_SYMBOL_METADATA')

    def test_duplicate_nan_and_ohlc(self):
        s=snap(); b=s.timeframes[0].candles
        for changed,code in [(b+(b[-1],),'NON_MONOTONIC_TIMESTAMPS'), (b[:-1]+(replace(b[-1],close=float('nan')),),'NONFINITE_PRICE'),(b[:-1]+(replace(b[-1],high=0),),'INVALID_OHLC')]:
            r=analyze(replace(s,timeframes=(TimeframeData('M15',changed),)))
            self.assertEqual(r['reasons'][0]['code'],code)

    def test_stale_quote_leaves_history_valid(self):
        s=snap(); r=analyze(replace(s,quote=replace(s.quote,time=s.as_of_utc-121)))
        self.assertEqual(r['analysis_status'],'valid')
        self.assertEqual(r['live_feed_status'],'stale')
        self.assertIsNone(r['market_context']['live_location'])
        self.assertIsNone(r['market_context']['spread_price'])

    def test_future_quote_not_mixed_with_history(self):
        s=snap(); r=analyze(replace(s,quote=replace(s.quote,time=s.as_of_utc+1)))
        self.assertEqual(r['live_feed_status'],'unknown')
        self.assertIsNone(r['market_context']['bid'])

    def test_spread_units(self):
        r=analyze(snap()); m=r['market_context']
        self.assertAlmostEqual(m['spread_points'],2)
        self.assertAlmostEqual(m['spread_atr_ratio'],m['spread_price']/r['timeframes']['M15']['volatility']['atr14'])

    def test_gap_with_and_without_schedule(self):
        b=bars(); s=snap(b[:270]+b[275:])
        self.assertEqual(analyze(s)['analysis_status'],'degraded')
        always=SessionWindow('broker','UTC',tuple(range(7)),0,1440)
        self.assertEqual(analyze(replace(s,sessions=(always,)))['analysis_status'],'unavailable')

    def test_dst_session(self):
        session=SessionWindow('New York','America/New_York',tuple(range(7)),9*60,17*60)
        def stamp(text): return datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp()
        self.assertFalse(session.contains(stamp('2026-03-07T13:30:00')))
        self.assertTrue(session.contains(stamp('2026-03-08T13:30:00')))

    def test_weekend_gap_is_expected_when_schedule_known(self):
        start=datetime(2026,9,14,tzinfo=timezone.utc).timestamp()
        session=SessionWindow('broker','UTC',(0,1,2,3,4),0,1440)
        times=[start+i*900 for i in range(8*96) if session.contains(start+i*900)]
        b=tuple(Candle(int(t),100,101,99,100) for t in times)
        s=replace(snap(b),sessions=(session,))
        self.assertEqual(analyze(s)['analysis_status'],'valid')
        self.assertIn('EXPECTED_SESSION_GAP',[r['code'] for r in analyze(s)['reasons']])


class ZoneTests(unittest.TestCase):
    def test_merge_width_and_activation(self):
        swings=[dict(id=str(i),kind='high',price=100+i*.4,occurrence_index=i,atr_at_confirmation=2,confirmed_at_utc=f'2026-01-01T00:0{i}:00Z') for i in range(8)]
        zones=zones_from_swings(swings,8,.01,CFG)
        self.assertTrue(all(z['upper']-z['lower'] <= z['max_width'] for z in zones))
        self.assertEqual(sum(len(z['source_swing_ids']) for z in zones),8)
        for z in zones:
            self.assertEqual(z['active_from_utc'],max(swings[int(i)]['confirmed_at_utc'] for i in z['source_swing_ids']))

    def test_nearest_edge_distance(self):
        z=[dict(id='a',kind='support',lower=90,upper=100),dict(id='b',kind='support',lower=100.5,upper=101)]
        r=location(100.1,z,2,.25)
        self.assertEqual(r['nearest_support']['zone']['id'],'a')
        self.assertEqual(r['state'],'near_support')

    def test_breakout_precedence_and_no_new_zone_break(self):
        b=[Candle(1,100,101,99,100),Candle(2,104,105,103,104)]
        z=dict(id='r',kind='resistance',lower=99,upper=101,source_swing_ids=['a','b'])
        structure=dict(state='rising',zones=[z])
        v=dict(state='elevated',atr14=2)
        self.assertEqual(regime(b,{'state':'up'},structure,v,[z],CFG)[0],'breakout_candidate')
        self.assertEqual(regime(b,{'state':'up'},structure,v,[],CFG)[0],'trending_up')

    def test_range_requires_two_touches_each_side(self):
        zones=[dict(kind='support',lower=90,upper=92,source_swing_ids=['a','b']),dict(kind='resistance',lower=108,upper=110,source_swing_ids=['c','d'])]
        b=[Candle(1,100,101,99,100),Candle(2,100,101,99,100)]
        args=(b,{'state':'flat_mixed'},{'state':'mixed','zones':zones},{'state':'normal','atr14':2},[],CFG)
        self.assertEqual(regime(*args)[0],'range')
        zones[0]['source_swing_ids']=['a']
        self.assertEqual(regime(*args)[0],'mixed')


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict('os.environ', {'MT5_TIMESTAMP_TIMEZONE': 'UTC'})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_exact_symbol_metadata_and_closed_filter(self):
        mt=Mock(); mt.symbol_info.return_value=SimpleNamespace(point=.01,trade_tick_size=.01,digits=2)
        mt.copy_rates_from_pos.return_value=[dict(time=900,open=1,high=2,low=0,close=1,tick_volume=1),dict(time=1800,open=1,high=2,low=0,close=1,tick_volume=1)]
        mt.symbol_info_tick.return_value=None
        result=capture_snapshot(mt,'XAUUSDm',1800,CFG)
        self.assertEqual(result.symbol,'XAUUSDm')
        self.assertEqual(len(result.timeframes[0].candles),1)
        self.assertEqual(len(result.timeframes[1].candles),0)

    def test_endpoint_no_api_key(self):
        with patch.dict('os.environ',{},clear=True),patch.object(main,'market_snapshot',return_value=snap()):
            self.assertEqual(main.technical('XAUUSD')['engine_version'],'ta-v1.0.0')

    def test_ai_explains_one_observation_with_matching_timestamp(self):
        import json
        observation=analyze(snap())
        client=Mock()
        client.responses.create.return_value=SimpleNamespace(output_text='Explanation')
        with patch.dict('os.environ',{'OPENAI_API_KEY':'test'}),patch.object(main,'technical',return_value=observation) as technical,patch.dict('sys.modules',{'openai':SimpleNamespace(OpenAI=lambda:client)}):
            result=main.analyze(main.AnalysisRequest(symbol='XAUUSD'))
        technical.assert_called_once_with('XAUUSD')
        self.assertEqual(result['quote_time'],observation['market_context']['quote_time_utc'])
        self.assertEqual(json.loads(client.responses.create.call_args.kwargs['input'])['technical_observation'],observation)

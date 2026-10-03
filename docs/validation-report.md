# Technical Analysis Engine â€” validation report

Verified 4 October 2026 (Africa/Johannesburg). Engine `ta-v1.0.0`; defaults unchanged.

## Native indicator parity

Source: MT5 build 6231, native iMA EMA20/EMA50 (PRICE_CLOSE, shift 0) and iATR14. Export captured 2026-09-29T06:35:23Z. Closed bars only.

Four instruments Ã— M5, M15, H1, H4: **24,016 evaluated bars, zero failures**. Each comparison checks all three indicators after a 500-bar engine warmup. Tolerance: max(2 ticks, 1e-6 Ã— absolute close).

| Indicator | Largest absolute difference (price units, across all symbols) |
|---|---:|
| ema20 | 5.82076609135e-11 |
| ema50 | 3.15734214382e-05 |
| atr14 | 5.40012479178e-12 |

MT5 native ATR14 agrees with the v1 rolling-mean TR implementation in this exported dataset. EMA50 retains a small initialization difference from its longer terminal history, within tolerance. This verifies this build/data/configuration; it is not a guarantee for different broker revisions or indicator implementations.

## Chronological replay

**2,000 observations passed causal equivalence**: 250 bars in each of two non-overlapping periods per instrument. Each as-of replay equals analysis of only the bars closed at that instant. Later periods were evaluated with unchanged defaults; no tuning was performed. Durations and per-state counts are retained in the JSON report.

| Symbol | Period (UTC) | Transitions | One-bar flicker rate | Status |
|---|---|---:|---:|---|
| XAUUSD_i | 2026-09-14T09:45:00Z â€“ 2026-09-17T03:00:00Z | 59 | 27.6% | degraded |
| XAUUSD_i | 2026-09-24T13:15:00Z â€“ 2026-09-29T06:30:00Z | 73 | 47.2% | degraded |
| BTCUSD | 2026-09-18T20:45:00Z â€“ 2026-09-21T11:00:00Z | 66 | 53.8% | valid |
| BTCUSD | 2026-09-26T16:15:00Z â€“ 2026-09-29T06:30:00Z | 79 | 44.9% | valid |
| GBPUSD_i | 2026-09-14T20:45:00Z â€“ 2026-09-17T11:00:00Z | 61 | 38.3% | degraded |
| GBPUSD_i | 2026-09-24T16:15:00Z â€“ 2026-09-29T06:30:00Z | 78 | 44.2% | degraded |
| EURUSD_i | 2026-09-14T20:45:00Z â€“ 2026-09-17T11:00:00Z | 61 | 36.7% | degraded |
| EURUSD_i | 2026-09-24T16:15:00Z â€“ 2026-09-29T06:30:00Z | 87 | 41.9% | degraded |

Flicker is the fraction of completed interior regime runs lasting one bar; first/last runs are censored. These rates show material state churn. They are measured behavior, not evidence that the defaults are optimal or that a strategy is profitable. FX/metals are degraded because missing calendar intervals have no authoritative broker schedule; data is not filled or fabricated.

## Time and live integration

- Native TimeTradeServer âˆ’ TimeGMT at export: **10,800 seconds**. Local `.env` now explicitly selects `MT5_TIMESTAMP_TIMEZONE=Etc/GMT-3`; UTC is still the core contract. This fixed setting must be reverified if the broker changes offset; no historical DST schedule was inferred.
- Display timestamps use `Africa/Johannesburg` (Pretoria). Freshness uses server-reported ages plus monotonic elapsed time, independent of PC/browser wall-clock changes.
- Backend UTC is checked against two HTTPS sources and advanced monotonically. Resync every five minutes, bounded cached use for fifteen minutes, then fail closed. No silent fallback to PC time.
- A tick newer than the as-of instant is replaced only by an actual earlier MT5 tick, never by rewriting its timestamp.
- Live smoke check: all four resolved symbols produce structured results. BTCUSD quote is fresh; the Friday FX/metals quotes are stale during this weekend check. Session status remains unknown without a verified calendar. BTC history refreshed after the terminal initially returned cached bars.

## Checks and remaining operational limits

- **46 Python tests and 9 frontend tests passed.** Regression suites cover clock consensus/outage, broker offset, DST ambiguity, timestamp boundaries, stale-state behavior, formulas, and request races.
- Real dashboard browser check passed: Pretoria timestamps, stale-history visibility, quote statuses, and no client console errors.
- AI explanation consumes one technical observation and returns that same observation with its prose; no AI network call was needed for this validation.
- Broker session/holiday scheduling is deliberately unknown unless an authoritative schedule is supplied. A fixed broker timezone is explicit configuration, not automatic DST discovery.
- Market-data caches may lag when an MT5 symbol/timeframe first loads; stale history is reported, not synthesized.
- No order functions were used. No synthetic data is connected to production routes.

## Reproducibility

Native CSV SHA-256: `f3e38bd9861fae7652953a5cf3d7ec385263eaecbfdab66b6c284bbf04294804`.
Config SHA-256: `4a5b435559b00f11eb656c57888dd5cccc3bc330a6900a32b31cddcb9bc81d9a`.

The terminal export files are `MQL5/Files/companion-reference.csv` and `companion-clock.csv`. Re-run `validation/check_reference.py` with those files and `validation/metadata.json`; the detailed measured results are in `validation/reference-report.json`. The exporter source is `validation/ExportTechnicalReference.mq5`.

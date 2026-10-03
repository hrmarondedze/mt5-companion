# Technical engine v1 implementation and acceptance

Implementation: `ta-v1.0.0`, schema `1.0`, default config `default-v1`.
The full configuration and SHA-256 hash accompany every observation. Numeric
values are unrounded in engine JSON; canonical JSON sorts keys, rejects NaN,
and uses Python's deterministic float serialization. The dashboard rounds prices
to tick size/digits and non-price evidence to six decimals. Keep the same Python
runtime when demanding byte-identical serialization across machines.

## Inputs and calculation policy

Each immutable snapshot carries exact broker symbol, point, tick size, digits,
as-of UTC seconds, separate timeframe tuples, optional timestamped quote,
connectivity, and optional explicit broker session windows. The adapter filters
closed candles individually, rather than discarding the last element. The pure
core also filters, supporting replay with future bars in the source dataset.

Default warmup is 250 closed bars per active timeframe, with a bounded 500-bar
calculation window. EMA20/50 seed from the SMA of the first complete window in
that same segment. Live and replay both select the last 500 bars at each as-of.
EMA50 slope spans ten closed bars. ATR14 is the simple rolling mean of 14 true
ranges, beginning with bar 1's previous close; bar 0 has no TR. Relative ATR
uses the median of the preceding 50 ATR values, excluding the current value.
Zero/negative current ATR or baseline makes the timeframe unavailable.

Trend uses strict separation/slope deadbands and close vs EMA50. Momentum uses
six closes/five changes, separate signed displacement and path efficiency,
and an independent single-bar-spike flag. Formula periods and smoothing are
part of engine version; changing them requires an engine version change.
Numerical thresholds are configurable and recorded by config hash.

## Causal structure, zones, and regime

Strict N=2 swings become visible at the close of the second following bar.
Occurrence timestamps are bar opens; confirmation timestamps are bar closes.
Both last-two-high and last-two-low comparisons are exposed. Equal neighbors
never produce swings. A timeframe can be valid with insufficient swings.

Zones use swings occurring within the latest 100 closed bars and positive ATR
at confirmation. Initial half-width is max(0.25 ATR, 2 ticks). The deterministic
oldest-first policy unions overlapping same-side zones only when the union is
no wider than the strictest source cap: max(1.5 source-confirmation ATR, 4 ticks).
Refused merges remain separate. Every source is retained. A merged zone's
active time is the newest contributing confirmation, so its expanded geometry
is never displayed retroactively. Replay recomputes each historical snapshot;
do not draw final-snapshot zones across earlier history. The dashboard draws
current M15 zone geometry only from its active timestamp onward.

Breakout detection compares the last two closes with zones computed from the
history **before** the last bar. Inside-to-outside crosses must clear 0.10 current
ATR and have elevated volatility. These take precedence over trend/structure.
Range requires flat/mixed trend, at least two confirmed same-side swings in each
of two non-overlapping boundary zones, last close within their outer bounds,
and no newly crossed active buffered boundary. Mixed is the fallback.
HTF alignment compares primary/HTF trend states and never overwrites the primary
regime. Momentum and volatility are exposed as separate qualifiers.

Nearest zones minimize distance to their edges, including zero inside a zone.
Signed distance is negative below a zone and positive above it. `between_zones`
means zones exist but none is within the near threshold; it does not guarantee
that price is geometrically bracketed by both sides.

## Quality and session policy

Invalid metadata, malformed OHLC, duplicate/disordered timestamps, insufficient
warmup, or nonpositive ATR yield null readings with stable reason codes.
Primary status is independent of missing M5/HTF status. Quotes after as-of are
excluded. Stale/missing/disconnected quotes do not invalidate historical
readings; spread and live location are null with reasons. Fresh quotes expose
bid and ask locations separately and spread in price, points, and price/ATR units.

No Weltrade instrument calendar is assumed. Default session is `unknown`, even
for BTCUSD CFDs. Missing intervals without a schedule produce degraded history,
not guessed closures. With explicit IANA-zone broker windows, expected closed
intervals are allowed; missing open-session bars degrade the timeframe, and a
run of four or more makes it unavailable. The check includes trailing missing
closed bars. Default quote freshness is 120 seconds; candle-age diagnostics use
one timeframe duration plus 120 seconds. Schedule windows support overnight
sessions and DST via `zoneinfo`/`tzdata`. Windows are caller-supplied inputs;
there is no built-in broker holiday calendar or schedule-discovery integration.
Supply an authoritative schedule only; omit it when holidays/breaks are unknown.

## Replay and indicator comparison

Run `python replay.py snapshot.json --output report.json`, optionally with
`--config config.json` and `--references mt5-reference.json`. Snapshot JSON is
the `dataclasses.asdict(MarketSnapshot)` format; all input timestamps are UTC
epoch seconds. `capture_history.py` exports this format from a responding MT5
terminal. Each replay step compares the full-dataset as-of result with an
equivalent closed-bars-only snapshot. Historical replay omits a lone latest
quote rather than backdating it. Reports include per-state counts, runs in bars
and trading-bar seconds, transitions, and completed-interior-run one-bar flicker
rate. Calendar gaps are not counted as time in a regime. Boundary runs are
censored. Missing periods and statuses remain visible in observations.

Reference JSON is a list of rows:

```json
[{"timeframe":"M15","as_of_utc":1790603100,
  "indicator_name":"MT5 iMA EMA20/EMA50 PRICE_CLOSE shift=0; iATR14, build recorded separately",
  "ema20":2650.45,"ema50":2642.10,"atr14":10.05}]
```

The numbers above illustrate the file format; they are not measured prices.
Use MT5 iMA(20/50, MODE_EMA, PRICE_CLOSE) and explicitly identified iATR(14)
outputs on the same broker symbol/timeframe and bar close. Record terminal build,
history start, and indicator settings in the indicator name or companion notes.
Compare after sufficient warmup, with tolerance max(2 ticks, 1e-6 Ã— absolute close).
The comparison harness measures discrepancies; it does not presume iATR uses
the engine's rolling smoothing. Any smoothing/seed difference must be documented
before claiming parity or changing the versioned formula.

## Acceptance status

Automated fixtures cover deterministic serialization, as-of/HTF closure,
live-equivalent replay, manually labeled strict/equal swings, nonpositive ATR,
flat path, spikes, metadata/OHLC failures, missing optional M5, stale/future quote,
spread units, IANA DST, gaps, bounded merging, nearest edge and breakout precedence.
Frontend checks cover obsolete responses and current-result errors.

Native parity and separate-period replays are now complete. See
[the measured validation report](validation-report.md) and
`validation/reference-report.json` for counts, errors, period boundaries,
regime durations, flicker rates, and limitations. No thresholds were tuned.

## Runtime time integration

`MT5_TIMESTAMP_TIMEZONE=Etc/GMT-3` is the explicit locally verified server-wall
interpretation, based on the native export clock record. It is distinct from
Pretoria display time (`Africa/Johannesburg`) and must be rechecked if the
broker changes seasonal offsets. Never infer an offset from an old quote.

The backend uses HTTPS UTC consensus with bounded monotonic caching. If no
trusted sample is available for fifteen minutes, it reports
`UTC_CLOCK_UNAVAILABLE`. The browser advances returned ages with
`performance.now()` and never uses PC wall time to decide freshness.

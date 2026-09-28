from dataclasses import asdict, dataclass
import hashlib
import json
import math


@dataclass(frozen=True)
class AnalysisConfig:
    config_id: str = 'default-v1'
    primary: str = 'M15'
    htf: str = 'H1'
    timing: str | None = 'M5'
    warmup_bars: int = 250
    history_bars: int = 500
    separation_deadband: float = .10
    slope_deadband: float = .05
    swing_radius: int = 2
    zone_lookback: int = 100
    zone_half_atr: float = .25
    zone_min_ticks: int = 2
    zone_max_width_atr: float = 1.5
    quiet_threshold: float = .8
    elevated_threshold: float = 1.3
    momentum_move: float = .25
    momentum_efficiency: float = .60
    spike_share: float = .70
    spike_atr: float = .75
    breakout_buffer_atr: float = .10
    near_atr: float = .25
    quote_max_age_seconds: float = 120
    history_grace_seconds: float = 120
    gap_unavailable_bars: int = 4

    def __post_init__(self):
        if self.primary != 'M15' or self.htf not in ('H1', 'H4') or self.timing not in ('M5', None):
            raise ValueError('Unsupported timeframe roles')
        if self.warmup_bars < 65 or self.history_bars < self.warmup_bars:
            raise ValueError('History must cover warmup and 50 previous ATR values (minimum 65 bars)')
        if self.swing_radius < 1 or self.zone_lookback < 2 * self.swing_radius + 1 or self.gap_unavailable_bars < 1:
            raise ValueError('Invalid swing, zone, or gap configuration')
        for key, value in asdict(self).items():
            if isinstance(value, (int, float)) and (not math.isfinite(value) or value < 0):
                raise ValueError(f'Invalid configuration: {key}')
        if not 0 < self.quiet_threshold <= self.elevated_threshold or not 0 <= self.momentum_efficiency <= 1 or not 0 <= self.spike_share <= 1:
            raise ValueError('Invalid threshold ordering')
        if self.zone_max_width_atr < 2 * self.zone_half_atr:
            raise ValueError('Zone width cap must contain initial zone')

    @property
    def active_timeframes(self):
        return (self.primary, self.htf) + ((self.timing,) if self.timing else ())

    @property
    def config_hash(self):
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True, separators=(',', ':')).encode()).hexdigest()

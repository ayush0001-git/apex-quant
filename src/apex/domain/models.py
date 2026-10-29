# apex-quant/src/apex/domain/models.py
"""Pure data contracts shared across all modules. Zero dependencies."""
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping
from .enums import Direction, GateStatus, KillReason, MarketRegime, Timeframe


@dataclass(frozen=True)
class Bar:
    """Normalized OHLCV Bar.
    is_closed: True ONLY when candle is finalised. First gate of causality.
    """
    symbol: str
    timeframe: Timeframe
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_closed: bool


@dataclass(frozen=True)
class FeatureSnapshot:
    """Read-only mathematical facts and patterns. Never outputs buy/sell."""
    symbol: str
    timestamp: datetime
    spot_price: float               # Spot price at decision time for P&L reconstruction
    indicators: Mapping[str, float]
    patterns: tuple[str, ...]
    confluence_score: float
    volume_ratio: float
    regime: MarketRegime
    factor_exposures: Mapping[str, float] | None = None
    volatility_gate: float = 1.0


@dataclass(frozen=True)
class Forecast:
    """Probabilistic prediction bands from Kronos. Never outputs buy/sell."""
    symbol: str
    horizon_bars: int
    high_band: tuple[float, float]
    low_band: tuple[float, float]
    directional_prob: float
    model_version: str = "Kronos-base-v1"


@dataclass(frozen=True)
class DebateResult:
    """Adversarial synthesis from LLM desk."""
    action: Direction
    conviction: int
    entry_zone: tuple[float, float]
    stop_loss: float
    targets: tuple[float, ...]
    reasoning_hash: str
    confidence_score: float = 0.0
    agent_scores: Mapping[str, float] | None = None


@dataclass(frozen=True)
class TradeIntent:
    """Single proposed action produced ONLY by DecisionEngine."""
    symbol: str
    direction: Direction
    entry: float
    stop: float
    targets: tuple[float, ...]
    conviction: int
    feature_snapshot: FeatureSnapshot
    forecast: Forecast | None
    debate: DebateResult


@dataclass(frozen=True)
class RiskDecision:
    """Decision produced ONLY by RiskGate (Pure Math, Zero LLM)."""
    status: GateStatus
    reason: str
    kill_reason: KillReason
    position_size: float | None
    max_capital_risk_pct: float
    net_rr_ratio: float
    estimated_statutory_friction: float
    dynamic_slippage_bps: float = 5.0
    portfolio_var_95_pct: float = 0.0
    portfolio_cvar_95_pct: float = 0.0
    defensive_multiplier: float = 1.0


@dataclass(frozen=True)
class AuditRecord:
    """Immutable trade log record."""
    audit_id: str
    timestamp_utc: datetime
    algo_id: str
    symbol: str
    intent: TradeIntent
    risk: RiskDecision

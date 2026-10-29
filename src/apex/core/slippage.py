# apex-quant/src/apex/core/slippage.py
"""Dynamic Slippage & Market Impact Engine.

Replaces naive static slippage models (fixed 5 bps) with an institutional
market microstructure model incorporating:
1. Kyle's Lambda square-root price impact law: Impact ~ sigma * sqrt(OrderSize / ADV)
2. Volatility scaling: Slippage widens during high realized volatility / gap events.
3. Volume shock scaling: Slippage widens when trading in thin volume or during volume surges.
4. Hard regulatory bounds: Clamped between min_slippage_pct and max_slippage_pct.
"""
from dataclasses import dataclass
import math
from typing import Optional
from ..domain.config import FrictionSettings


@dataclass(frozen=True)
class SlippageQuote:
    """Detailed slippage cost estimation."""
    slippage_pct: float             # In decimal (e.g. 0.0008 = 8 bps)
    slippage_bps: float             # In basis points (e.g. 8.0)
    slippage_inr: float             # Rupee amount for the turnover
    base_bps: float
    volatility_penalty_bps: float
    impact_penalty_bps: float


class DynamicSlippageModel:
    """Calculates realistic dynamic execution slippage for Indian equities."""

    def __init__(self, friction_settings: Optional[FrictionSettings] = None) -> None:
        self.base_slippage = friction_settings.default_slippage_pct if friction_settings else 0.0005
        self.min_slippage = getattr(friction_settings, "min_slippage_pct", 0.0002) if friction_settings else 0.0002
        self.max_slippage = getattr(friction_settings, "max_slippage_pct", 0.0050) if friction_settings else 0.0050
        self.vol_factor = getattr(friction_settings, "slippage_vol_factor", 0.5) if friction_settings else 0.5
        self.impact_factor = getattr(friction_settings, "slippage_impact_factor", 0.1) if friction_settings else 0.1

    def calculate_slippage_pct(
        self,
        volume_ratio: float = 1.0,
        volatility_pct: float = 0.015,
        participation_rate: float = 0.001,
        baseline_volatility: float = 0.015,
    ) -> float:
        """Calculate slippage percentage based on volume, volatility, and order participation.
        
        Args:
            volume_ratio: Current bar volume / 20-period average volume.
            volatility_pct: Estimated bar or daily volatility (ATR/spot or daily return std).
            participation_rate: Order size relative to average bar/daily volume (turnover / ADV).
            baseline_volatility: Benchmark normal volatility (1.5% for liquid Nifty stocks).
        """
        # 1. Base slippage (e.g. 5 bps = 0.0005)
        base = self.base_slippage

        # 2. Volatility penalty: As volatility expands above baseline, spread widens
        vol_ratio = max(0.2, volatility_pct / (baseline_volatility + 1e-8))
        vol_multiplier = 1.0 + self.vol_factor * max(0.0, vol_ratio - 1.0)

        # 3. Volume ratio penalty: Low volume = wide spread; abnormal volume surge = fast market slippage
        # In Indian markets, both illiquidity (vol_ratio < 0.5) and violent breakouts (vol_ratio > 2.0) inflate slippage
        vol_shock = 0.0
        if volume_ratio < 0.6:
            vol_shock = (0.6 - volume_ratio) * 0.5  # Illiquidity spread widening
        elif volume_ratio > 1.8:
            vol_shock = min(1.0, (volume_ratio - 1.8) * 0.3)  # Volatile queue-jumping slippage

        # 4. Kyle's Lambda square-root market impact: Impact = k * sqrt(Participation)
        safe_part = max(0.0, min(0.5, participation_rate))
        impact_pct = self.impact_factor * math.sqrt(safe_part) * 0.01

        # 5. Combined effective slippage
        effective_pct = (base * vol_multiplier * (1.0 + vol_shock)) + impact_pct

        # 6. Strict bounds
        return max(self.min_slippage, min(self.max_slippage, effective_pct))

    def estimate_slippage(
        self,
        turnover: float,
        shares: float,
        spot_price: float,
        volume_ratio: float = 1.0,
        volatility_pct: float = 0.015,
        adv_turnover: float = 50_000_000.0,
    ) -> SlippageQuote:
        """Compute full SlippageQuote including rupee cost and basis points."""
        participation = turnover / (adv_turnover + 1e-8) if adv_turnover > 0 else 0.001
        slippage_pct = self.calculate_slippage_pct(
            volume_ratio=volume_ratio,
            volatility_pct=volatility_pct,
            participation_rate=participation,
        )

        base_bps = self.base_slippage * 10_000
        total_bps = slippage_pct * 10_000
        slippage_inr = round(turnover * slippage_pct, 2)

        vol_penalty = max(0.0, (slippage_pct - self.base_slippage) * 10_000 * 0.6)
        impact_penalty = max(0.0, total_bps - base_bps - vol_penalty)

        return SlippageQuote(
            slippage_pct=round(slippage_pct, 6),
            slippage_bps=round(total_bps, 2),
            slippage_inr=slippage_inr,
            base_bps=round(base_bps, 2),
            volatility_penalty_bps=round(vol_penalty, 2),
            impact_penalty_bps=round(impact_penalty, 2),
        )


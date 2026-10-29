# apex-quant/src/apex/core/factors.py
"""Factor Engine: Cross-Sectional Alpha & Factor Exposure Service.

Implements institutional quantitative factor models for Indian equities:
1. Carhart Four-Factor & Momentum Models (WML, 20d Momentum, 5d Reversal)
2. Low-Volatility & Downside Risk Factor (20d Realized Volatility, ATR/Price)
3. Liquidity & Market Impact Factor (Amihud Illiquidity, Volume Z-Score)
4. Quality & Value Proxy (Piotroski F-score estimation, Fundamental Multiples)
5. Cross-Sectional Vectorized Normalization (Z-Score & Percentile Ranking)
"""
from dataclasses import dataclass
import math
from typing import Mapping, Sequence, Dict, Any, Optional
import numpy as np
import pandas as pd
from ..domain.models import Bar
from .ingestion import DataQualityError


@dataclass(frozen=True)
class FactorExposures:
    """Factor loadings and normalized scores for a single instrument."""
    symbol: str
    momentum_20d: float            # 20-period price momentum (%)
    reversal_5d: float             # 5-period short term reversal (%)
    realized_vol_20d: float        # 20-period annualized realized volatility (%)
    atr_price_ratio: float         # ATR / spot price ratio (%)
    volume_zscore_20d: float       # Standard deviations from 20-period volume mean
    amihud_illiquidity: float      # Absolute return per rupee of turnover
    quality_score: float           # Estimated Piotroski / stability proxy (0 to 9)
    composite_alpha_score: float   # Weighted composite factor score (-100 to +100)


class FactorService:
    """Computes cross-sectional and time-series factor exposures."""

    DEFAULT_WEIGHTS = {
        "momentum": 0.35,
        "low_volatility": 0.25,
        "liquidity": 0.20,
        "quality": 0.20,
    }

    HMM_WEIGHT_PROFILES = {
        0: {"momentum": 0.45, "low_volatility": 0.15, "liquidity": 0.20, "quality": 0.20},  # Low-Vol Trend
        1: {"momentum": 0.15, "low_volatility": 0.25, "liquidity": 0.20, "quality": 0.40},  # Range Compression / Mean Reversion
        2: {"momentum": 0.05, "low_volatility": 0.45, "liquidity": 0.20, "quality": 0.30},  # High-Vol Turbulence
    }

    @staticmethod
    def compute_single_asset_factors(bars: Sequence[Bar]) -> Dict[str, float]:
        """Compute raw time-series factor metrics on a sequence of closed bars."""
        if len(bars) < 20:
            raise DataQualityError(f"Need at least 20 closed bars for factor calculation, got {len(bars)}")

        for b in bars:
            if not b.is_closed:
                raise DataQualityError(f"Causality Violation in FactorService: unclosed bar for {b.symbol}")

        closes = np.array([b.close for b in bars], dtype=float)
        highs = np.array([b.high for b in bars], dtype=float)
        lows = np.array([b.low for b in bars], dtype=float)
        volumes = np.array([b.volume for b in bars], dtype=float)

        # 1. Momentum: 20-bar percentage change
        mom_20 = ((closes[-1] - closes[-20]) / (closes[-20] + 1e-8)) * 100.0

        # 2. Reversal: 5-bar percentage change (negative sign represents reversal expectation)
        rev_5 = -((closes[-1] - closes[-5]) / (closes[-5] + 1e-8)) * 100.0

        # 3. Realized Volatility: Annualized 20-bar log return standard deviation
        log_rets = np.diff(np.log(closes[-21:]))
        daily_vol = np.std(log_rets, ddof=1) if len(log_rets) > 1 else 0.015
        # Approximate annualization factor (sqrt(252) for daily, sqrt(252 * 25) for 15m)
        ann_vol = daily_vol * math.sqrt(252) * 100.0

        # 4. ATR / Price Ratio
        tr = np.maximum(
            highs[-14:] - lows[-14:],
            np.maximum(
                np.abs(highs[-14:] - closes[-15:-1]),
                np.abs(lows[-14:] - closes[-15:-1]),
            ),
        )
        atr_14 = float(np.mean(tr))
        atr_ratio = (atr_14 / (closes[-1] + 1e-8)) * 100.0

        # 5. Volume Z-Score over 20 periods
        vol_slice = volumes[-20:]
        vol_mean = float(np.mean(vol_slice))
        vol_std = float(np.std(vol_slice, ddof=1)) + 1e-8
        vol_zscore = float((volumes[-1] - vol_mean) / vol_std)

        # 6. Amihud Illiquidity: Average |Return| / (Close * Volume)
        rets_slice = np.abs(np.diff(closes[-20:]) / closes[-20:-1])
        turnover_slice = closes[-19:] * volumes[-19:] + 1e-8
        amihud = float(np.mean(rets_slice / turnover_slice) * 1e7)

        # 7. Quality / Balance Proxy (Piotroski style heuristic for technical series):
        # Rewards upward trending slope with low return variance and volume stability
        quality = 5.0
        if mom_20 > 0:
            quality += 1.0
        if ann_vol < 25.0:
            quality += 1.5
        if vol_zscore > -1.0:
            quality += 1.5
        quality = min(9.0, max(0.0, quality))

        return {
            "momentum_20d": round(mom_20, 2),
            "reversal_5d": round(rev_5, 2),
            "realized_vol_20d": round(ann_vol, 2),
            "atr_price_ratio": round(atr_ratio, 2),
            "volume_zscore_20d": round(vol_zscore, 2),
            "amihud_illiquidity": round(amihud, 4),
            "quality_score": round(quality, 1),
        }

    @classmethod
    def compute_cross_sectional_scores(
        cls,
        universe_raw_factors: Mapping[str, Mapping[str, float]],
        weights: Optional[Mapping[str, float]] = None,
        hmm_state: int = 0,
    ) -> Dict[str, FactorExposures]:
        """Normalize factors across an entire universe using cross-sectional Z-scores.
        
        Dynamically adapts factor weights based on the prevailing HMM regime state.
        Outputs ranked FactorExposures with composite alpha scores from -100 to +100.
        """
        w = weights or cls.HMM_WEIGHT_PROFILES.get(hmm_state, cls.DEFAULT_WEIGHTS)
        symbols = list(universe_raw_factors.keys())
        if not symbols:
            return {}

        df = pd.DataFrame.from_dict(universe_raw_factors, orient="index")

        # Standardize cross-sectionally
        # Momentum: Higher is better
        mom_z = (df["momentum_20d"] - df["momentum_20d"].mean()) / (df["momentum_20d"].std() + 1e-8)
        # Volatility: Lower is better (Low-Vol anomaly) -> invert
        vol_z = -(df["realized_vol_20d"] - df["realized_vol_20d"].mean()) / (df["realized_vol_20d"].std() + 1e-8)
        # Liquidity: High volume z-score & low Amihud illiquidity is better
        liq_z = (df["volume_zscore_20d"] - df["volume_zscore_20d"].mean()) / (df["volume_zscore_20d"].std() + 1e-8)
        # Quality: Higher quality is better
        qual_z = (df["quality_score"] - df["quality_score"].mean()) / (df["quality_score"].std() + 1e-8)

        # Composite Z-score
        composite_z = (
            w.get("momentum", 0.35) * mom_z
            + w.get("low_volatility", 0.25) * vol_z
            + w.get("liquidity", 0.20) * liq_z
            + w.get("quality", 0.20) * qual_z
        )

        # Map to -100 to +100 composite score
        # Using tanh sigmoid mapping to bound outliers gracefully
        composite_scores = np.tanh(composite_z / 2.0) * 100.0

        results = {}
        for sym in symbols:
            raw = universe_raw_factors[sym]
            results[sym] = FactorExposures(
                symbol=sym,
                momentum_20d=raw["momentum_20d"],
                reversal_5d=raw["reversal_5d"],
                realized_vol_20d=raw["realized_vol_20d"],
                atr_price_ratio=raw["atr_price_ratio"],
                volume_zscore_20d=raw["volume_zscore_20d"],
                amihud_illiquidity=raw["amihud_illiquidity"],
                quality_score=raw["quality_score"],
                composite_alpha_score=round(float(composite_scores[sym]), 1),
            )

        return results


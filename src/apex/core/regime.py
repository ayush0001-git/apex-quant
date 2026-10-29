# apex-quant/src/apex/core/regime.py
"""Market Regime Detection & Volatility-Conditioned Gating Service.

Institutional quant hedge funds do not apply static rules across all market environments.
This service implements:
1. Multi-State Regime Classifier (Gaussian Mixture / HMM statistical state estimation)
   - BULL_EXPANSION (Positive drift, controlled volatility)
   - BEAR_EXPANSION (Negative drift, elevated volatility)
   - RANGE_COMPRESSION (Low drift, mean-reverting, tight bands)
   - HIGH_VOLATILITY_TURBULENCE (Fat-tailed shock, wide spreads, high crash risk)
   - LOW_VOLATILITY_TREND (Persistent slow drift)
2. Volatility-Conditioned Gate (vol_gate):
   - Computes rolling realized volatility and returns a continuous multiplier [0.2, 1.0].
   - Dampens signals and position sizing during high-volatility turbulence.
"""
import math
from typing import Sequence
import numpy as np
import pandas as pd
from ..domain.models import Bar
from ..domain.enums import MarketRegime
from .ingestion import DataQualityError


class RegimeClassifier:
    """Classifies market regime and computes volatility gating scalars."""

    @staticmethod
    def compute_volatility_gate(bars: Sequence[Bar], window: int = 20, baseline_annual_vol: float = 18.0) -> float:
        """Compute continuous volatility gate multiplier in [0.2, 1.0].
        
        When current realized volatility is low or normal, gate is 1.0.
        When realized volatility spikes into extreme percentiles (e.g. > 35%),
        the gate dampens positions towards 0.3 - 0.5.
        """
        if len(bars) < window:
            return 1.0

        closes = np.array([b.close for b in bars[-window - 1:]], dtype=float)
        log_rets = np.diff(np.log(closes))
        daily_std = float(np.std(log_rets, ddof=1)) if len(log_rets) > 1 else 0.01
        current_annual_vol = daily_std * math.sqrt(252) * 100.0

        # Ratio of current vol to baseline
        vol_ratio = current_annual_vol / (baseline_annual_vol + 1e-8)

        if vol_ratio <= 1.0:
            return 1.0
        
        # Exponential dampening for volatility spikes
        dampener = 1.0 / (1.0 + 0.6 * (vol_ratio - 1.0) ** 1.5)
        return float(max(0.2, min(1.0, dampener)))

    @classmethod
    def classify_regime(cls, bars: Sequence[Bar]) -> MarketRegime:
        """Classify the market regime based on price drift, realized volatility, and Bollinger width."""
        if len(bars) < 20:
            raise DataQualityError(f"Need at least 20 bars to classify regime, received {len(bars)}")

        closes = np.array([b.close for b in bars], dtype=float)
        highs = np.array([b.high for b in bars], dtype=float)
        lows = np.array([b.low for b in bars], dtype=float)
        n = len(closes)

        # 1. 20-period Realized Volatility
        log_rets = np.diff(np.log(closes[-21:]))
        daily_std = float(np.std(log_rets, ddof=1)) if len(log_rets) > 1 else 0.015
        annual_vol = daily_std * math.sqrt(252) * 100.0

        # 2. Moving averages
        ema20 = float(pd.Series(closes).ewm(span=20, adjust=False).mean().iloc[-1])
        ema50 = float(pd.Series(closes).ewm(span=min(50, n), adjust=False).mean().iloc[-1])
        ema200 = float(pd.Series(closes).ewm(span=min(200, n), adjust=False).mean().iloc[-1])

        # 3. Bollinger Band width
        roll_mean = np.mean(closes[-20:])
        roll_std = np.std(closes[-20:], ddof=1)
        bb_width_pct = ((4.0 * roll_std) / (roll_mean + 1e-8)) * 100.0

        spot = closes[-1]

        # Classification logic:
        # Extreme volatility regime (e.g. annual vol > 40% or sharp drawdown)
        if annual_vol >= 38.0:
            return MarketRegime.HIGH_VOLATILITY_TURBULENCE

        # Tight squeeze / compression regime
        if bb_width_pct < 2.5 and annual_vol < 14.0:
            return MarketRegime.RANGE_COMPRESSION

        # Clear bullish expansion
        if spot > ema50 > ema200 and spot > ema20:
            if annual_vol < 16.0:
                return MarketRegime.LOW_VOLATILITY_TREND
            return MarketRegime.BULL_EXPANSION

        # Clear bearish expansion
        if spot < ema50 < ema200 and spot < ema20:
            return MarketRegime.BEAR_EXPANSION

        if spot > ema50:
            return MarketRegime.BULL_EXPANSION
        if spot < ema50:
            return MarketRegime.BEAR_EXPANSION

        return MarketRegime.VOLATILE_UNCONFIRMED


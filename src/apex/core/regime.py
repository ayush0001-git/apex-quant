# apex-quant/src/apex/core/regime.py
"""Market Regime Detection & Volatility-Conditioned Gating Service.

Institutional quantitative hedge funds do not apply static rules across all market environments.
This service implements:
1. Multi-State Regime Classifier (Gaussian Mixture / HMM statistical state estimation)
   - BULL_EXPANSION (Positive drift, controlled volatility)
   - BEAR_EXPANSION (Negative drift, elevated volatility)
   - RANGE_COMPRESSION (Low drift, mean-reverting, tight bands)
   - HIGH_VOLATILITY_TURBULENCE (Fat-tailed shock, wide spreads, high crash risk)
   - LOW_VOLATILITY_TREND (Persistent slow drift)
2. Gaussian HMM Regime Detector (3-state Hidden Markov Model via hmmlearn):
   - State 0: Low-Volatility Trend (Momentum alpha favored)
   - State 1: Range Compression / Mean Reverting (Mean-reversion alpha favored)
   - State 2: High-Volatility Turbulence (Capital preservation & quality/low-vol favored)
3. Volatility-Conditioned Gate (vol_gate):
   - Computes rolling realized volatility and returns a continuous multiplier [0.2, 1.0].
   - Dampens signals and position sizing during high-volatility turbulence.
"""
from dataclasses import dataclass
import math
from typing import Sequence, Tuple, Optional
import numpy as np
import pandas as pd
from ..domain.models import Bar
from ..domain.enums import MarketRegime
from .ingestion import DataQualityError

try:
    from hmmlearn.hmm import GaussianHMM
    HMMLEARN_AVAILABLE = True
except ImportError:
    HMMLEARN_AVAILABLE = False


@dataclass(frozen=True)
class HMMRegimeOutput:
    """Hidden Markov Model regime classification output."""
    state_id: int                           # 0: Low-Vol Trend, 1: Range Compression, 2: High-Vol Turbulence
    state_label: str                        # Human readable state label
    state_probabilities: Tuple[float, float, float]  # Posterior probabilities (p0, p1, p2)
    volatility_gate: float                  # Continuous vol gating scalar [0.2, 1.0]


class GaussianHMMRegimeDetector:
    """3-State Hidden Markov Model for unsupervised market regime identification."""

    STATE_LABELS = {
        0: "LOW_VOLATILITY_TREND",
        1: "RANGE_COMPRESSION_MEAN_REVERTING",
        2: "HIGH_VOLATILITY_TURBULENCE",
    }

    @classmethod
    def detect_regime(
        cls,
        bars: Sequence[Bar],
        window: int = 30,
    ) -> HMMRegimeOutput:
        """Fit or infer 3-state HMM regime from closed historical bars.
        
        Features:
        1. Log returns
        2. Rolling 5-bar realized volatility
        """
        if len(bars) < 20:
            return HMMRegimeOutput(
                state_id=0,
                state_label=cls.STATE_LABELS[0],
                state_probabilities=(1.0, 0.0, 0.0),
                volatility_gate=1.0,
            )

        closes = np.array([b.close for b in bars], dtype=float)
        log_rets = np.diff(np.log(closes))
        
        # Rolling volatility series
        roll_vol = pd.Series(log_rets).rolling(5, min_periods=2).std().fillna(0.01).values
        
        # Feature matrix (N, 2)
        X = np.column_stack([log_rets, roll_vol])

        if HMMLEARN_AVAILABLE and len(X) >= 25:
            try:
                model = GaussianHMM(
                    n_components=3,
                    covariance_type="diag",
                    n_iter=100,
                    random_state=42,
                    init_params="stmc",
                )
                model.fit(X)
                # Posterior state probabilities for the last bar
                posteriors = model.predict_proba(X)[-1]
                
                # Order states by mean variance so state 0=lowest vol, state 2=highest vol
                vol_means = [cov[1] for cov in model.covars_]
                sorted_indices = np.argsort(vol_means)
                
                reordered_probs = [float(posteriors[idx]) for idx in sorted_indices]
                current_state = int(np.argmax(reordered_probs))
                
                # Volatility gate scaled by turbulence state probability
                vol_gate = float(max(0.2, 1.0 - (0.7 * reordered_probs[2])))
                
                return HMMRegimeOutput(
                    state_id=current_state,
                    state_label=cls.STATE_LABELS.get(current_state, "UNKNOWN"),
                    state_probabilities=(round(reordered_probs[0], 3), round(reordered_probs[1], 3), round(reordered_probs[2], 3)),
                    volatility_gate=round(vol_gate, 3),
                )
            except Exception:
                pass

        # Analytical fallback if hmmlearn fails or sample size is tight
        ann_vol = float(np.std(log_rets[-10:], ddof=1) * math.sqrt(252) * 100.0) if len(log_rets) >= 10 else 15.0
        if ann_vol >= 32.0:
            state = 2
            probs = (0.1, 0.2, 0.7)
            gate = 0.4
        elif ann_vol < 14.0:
            state = 1
            probs = (0.2, 0.7, 0.1)
            gate = 1.0
        else:
            state = 0
            probs = (0.7, 0.2, 0.1)
            gate = 0.95

        return HMMRegimeOutput(
            state_id=state,
            state_label=cls.STATE_LABELS[state],
            state_probabilities=probs,
            volatility_gate=gate,
        )


class RegimeClassifier:
    """Classifies market regime and computes volatility gating scalars."""

    @staticmethod
    def compute_volatility_gate(bars: Sequence[Bar], window: int = 20, baseline_annual_vol: float = 18.0) -> float:
        """Compute continuous volatility gate multiplier in [0.2, 1.0]."""
        if len(bars) < window:
            return 1.0

        closes = np.array([b.close for b in bars[-window - 1:]], dtype=float)
        log_rets = np.diff(np.log(closes))
        daily_std = float(np.std(log_rets, ddof=1)) if len(log_rets) > 1 else 0.01
        current_annual_vol = daily_std * math.sqrt(252) * 100.0

        vol_ratio = current_annual_vol / (baseline_annual_vol + 1e-8)
        if vol_ratio <= 1.0:
            return 1.0
        
        dampener = 1.0 / (1.0 + 0.6 * (vol_ratio - 1.0) ** 1.5)
        return float(max(0.2, min(1.0, dampener)))

    @classmethod
    def classify_regime(cls, bars: Sequence[Bar]) -> MarketRegime:
        """Classify the market regime based on price drift, realized volatility, and Bollinger width."""
        if len(bars) < 20:
            raise DataQualityError(f"Need at least 20 bars to classify regime, received {len(bars)}")

        closes = np.array([b.close for b in bars], dtype=float)
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
        if annual_vol >= 38.0:
            return MarketRegime.HIGH_VOLATILITY_TURBULENCE

        if bb_width_pct < 2.5 and annual_vol < 14.0:
            return MarketRegime.RANGE_COMPRESSION

        if spot > ema50 > ema200 and spot > ema20:
            if annual_vol < 16.0:
                return MarketRegime.LOW_VOLATILITY_TREND
            return MarketRegime.BULL_EXPANSION

        if spot < ema50 < ema200 and spot < ema20:
            return MarketRegime.BEAR_EXPANSION

        if spot > ema50:
            return MarketRegime.BULL_EXPANSION
        if spot < ema50:
            return MarketRegime.BEAR_EXPANSION

        return MarketRegime.VOLATILE_UNCONFIRMED

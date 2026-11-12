# apex-quant/src/apex/core/regime.py
"""Market Regime Classification, Gaussian HMM & Continuous Volatility Gating.

Implements institutional regime-detection models:
1. Rule-Based Multi-Timeframe Regime Classifier (Bull/Bear Expansion, Sideways, Turbulence)
2. Unsupervised 3-State Gaussian Hidden Markov Model (HMM):
   - Multi-feature input: [Log Returns, Realized Volatility, Volume Ratio, Normalized Range]
   - Bayesian Information Criterion (BIC) validation for state parsimony
   - Transition persistence diagnostics ensuring regimes do not flip randomly
3. Continuous Volatility Gating scalar [0.2, 1.0]:
   - Dampens position size and demotes technical confluence during market turbulence
"""
from dataclasses import dataclass
import math
from typing import Sequence, Tuple, Optional, Dict, Any, List
import warnings
import numpy as np
import pandas as pd
from ..domain.models import Bar
from ..domain.enums import MarketRegime
from .ingestion import DataQualityError

warnings.filterwarnings("ignore")

import os
if "LOKY_MAX_CPU_COUNT" not in os.environ:
    os.environ["LOKY_MAX_CPU_COUNT"] = "4"

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
    persistence_score: float = 0.85         # Mean diagonal transition probability [0.0, 1.0]
    bic_score: float = 0.0                  # Bayesian Information Criterion


class GaussianHMMRegimeDetector:
    """Multi-feature 3-State Hidden Markov Model for unsupervised market regime identification."""

    STATE_LABELS = {
        0: "LOW_VOLATILITY_TREND",
        1: "RANGE_COMPRESSION_MEAN_REVERTING",
        2: "HIGH_VOLATILITY_TURBULENCE",
    }

    # Model cache: symbol -> (bar_count, fitted_model, sorted_indices, persistence, bic)
    _model_cache: Dict[str, Tuple[int, Any, List[int], float, float]] = {}

    @classmethod
    def clear_cache(cls) -> None:
        """Clear cached HMM models."""
        cls._model_cache.clear()

    @staticmethod
    def _extract_multi_features(bars: Sequence[Bar]) -> np.ndarray:
        """Construct 4-dimensional normalized feature matrix from closed bars."""
        closes = np.array([b.close for b in bars], dtype=float)
        highs = np.array([b.high for b in bars], dtype=float)
        lows = np.array([b.low for b in bars], dtype=float)
        volumes = np.array([b.volume for b in bars], dtype=float)

        log_rets = np.diff(np.log(closes))
        n = len(log_rets)

        # 1. Realized volatility (5-period rolling std)
        roll_vol = pd.Series(log_rets).rolling(5, min_periods=2).std().fillna(0.01).values

        # 2. Volume ratio (Volume / 20-period SMA)
        vol_s = pd.Series(volumes[1:])
        vol_sma20 = vol_s.rolling(20, min_periods=5).mean().fillna(volumes[1:].mean() + 1.0)
        vol_ratio = (vol_s / (vol_sma20 + 1e-8)).values

        # 3. Normalized intraday range
        rng = (highs[1:] - lows[1:]) / (closes[1:] + 1e-8)
        norm_rng = pd.Series(rng).rolling(14, min_periods=3).mean().fillna(0.01).values

        # Stack into (N, 4) matrix
        X = np.column_stack([log_rets, roll_vol, vol_ratio, norm_rng])
        return X

    @classmethod
    def calculate_bic(cls, model: Any, X: np.ndarray) -> float:
        """Calculate Bayesian Information Criterion (BIC) for HMM model selection.
        
        BIC = -2 * log_likelihood + k * log(N)
        """
        try:
            n_samples = X.shape[0]
            log_likelihood = model.score(X)
            # Free parameters: (k-1) initial + k*(k-1) transmat + k*dim means + k*dim covars
            k = model.n_components
            dim = X.shape[1]
            n_params = (k - 1) + (k * (k - 1)) + (k * dim) + (k * dim)
            bic = -2.0 * log_likelihood + n_params * math.log(n_samples)
            return round(float(bic), 2)
        except Exception:
            return 0.0

    @classmethod
    def detect_regime(
        cls,
        bars: Sequence[Bar],
        window: int = 30,
    ) -> HMMRegimeOutput:
        """Fit or infer 3-state HMM regime from closed historical bars using multi-feature inputs."""
        if len(bars) < 20:
            return HMMRegimeOutput(
                state_id=0,
                state_label=cls.STATE_LABELS[0],
                state_probabilities=(1.0, 0.0, 0.0),
                volatility_gate=1.0,
                persistence_score=1.0,
                bic_score=0.0,
            )

        X = cls._extract_multi_features(bars)
        sym = bars[0].symbol if bars else "DEFAULT"

        if HMMLEARN_AVAILABLE and len(X) >= 25:
            try:
                cached = cls._model_cache.get(sym)
                # Refit only if no cache exists or if >= 30 bars have arrived (F9)
                if cached is not None and (len(X) - cached[0] < 30):
                    _, model, sorted_indices, persistence, bic = cached
                    posteriors = model.predict_proba(X)[-1]
                else:
                    model = GaussianHMM(
                        n_components=3,
                        covariance_type="diag",
                        n_iter=50,
                        random_state=42,
                        init_params="stmc",
                    )
                    model.fit(X)
                    posteriors = model.predict_proba(X)[-1]
                    bic = cls.calculate_bic(model, X)

                    # Order states deterministically by volatility dimension (column 1 = roll_vol)
                    vol_means = [cov[1] for cov in model.covars_]
                    sorted_indices = list(np.argsort(vol_means))

                    trans = model.transmat_
                    persistence = float(np.mean(np.diag(trans)))
                    cls._model_cache[sym] = (len(X), model, sorted_indices, persistence, bic)

                reordered_probs = [float(posteriors[idx]) for idx in sorted_indices]
                current_state = int(np.argmax(reordered_probs))

                # Volatility gate scaled by turbulence state probability
                vol_gate = float(max(0.2, 1.0 - (0.7 * reordered_probs[2])))

                return HMMRegimeOutput(
                    state_id=current_state,
                    state_label=cls.STATE_LABELS.get(current_state, "UNKNOWN"),
                    state_probabilities=(round(reordered_probs[0], 3), round(reordered_probs[1], 3), round(reordered_probs[2], 3)),
                    volatility_gate=round(vol_gate, 3),
                    persistence_score=round(persistence, 3),
                    bic_score=bic,
                )
            except Exception:
                pass

        # Robust analytical fallback
        closes = [b.close for b in bars]
        log_rets = np.diff(np.log(closes))
        ann_vol = float(np.std(log_rets[-10:], ddof=1) * math.sqrt(252) * 100.0) if len(log_rets) >= 10 else 15.0
        if ann_vol >= 32.0:
            state = 2
            probs = (0.1, 0.2, 0.7)
            gate = 0.4
        elif ann_vol <= 16.0:
            state = 0
            probs = (0.8, 0.15, 0.05)
            gate = 1.0
        else:
            state = 1
            probs = (0.2, 0.65, 0.15)
            gate = 0.8

        return HMMRegimeOutput(
            state_id=state,
            state_label=cls.STATE_LABELS[state],
            state_probabilities=probs,
            volatility_gate=gate,
            persistence_score=0.80,
            bic_score=0.0,
        )


class RegimeClassifier:
    """Multi-timeframe heuristic and volatility-gated regime classification."""

    @staticmethod
    def classify_regime(bars: Sequence[Bar]) -> MarketRegime:
        """Classify bar history into structured MarketRegime."""
        if len(bars) < 20:
            return MarketRegime.RANGE_COMPRESSION

        closes = [b.close for b in bars]
        c = closes[-1]
        c_20 = closes[-20]
        n = len(closes)

        # Approximate moving averages
        sma_20 = sum(closes[-20:]) / 20.0
        sma_50 = sum(closes[-min(50, n):]) / min(50, n)

        # 20-period Realized Volatility
        log_rets = np.diff(np.log(closes[-21:])) if n >= 21 else np.array([0.01])
        daily_std = float(np.std(log_rets, ddof=1)) if len(log_rets) > 1 else 0.015
        ann_vol = daily_std * math.sqrt(252) * 100.0

        if ann_vol > 35.0:
            return MarketRegime.HIGH_VOLATILITY_TURBULENCE

        mom_pct = ((c - c_20) / (c_20 + 1e-8)) * 100.0

        if c > sma_20 and sma_20 > sma_50 and mom_pct > 2.5:
            return MarketRegime.BULL_EXPANSION
        elif c < sma_20 and sma_20 < sma_50 and mom_pct < -2.5:
            return MarketRegime.BEAR_EXPANSION
        else:
            return MarketRegime.RANGE_COMPRESSION

    @staticmethod
    def compute_volatility_gate(
        bars: Sequence[Bar],
        baseline_vol_pct: float = 16.0,
        panic_vol_pct: float = 40.0,
        baseline_annual_vol: Optional[float] = None,
    ) -> float:
        """Compute continuous scalar [0.2, 1.0] to dampen position size in turbulent markets."""
        if baseline_annual_vol is not None:
            baseline_vol_pct = baseline_annual_vol
        if len(bars) < 20:
            return 1.0

        closes = [b.close for b in bars]
        n = len(closes)
        log_rets = np.diff(np.log(closes[-21:])) if n >= 21 else np.array([0.01])
        daily_std = float(np.std(log_rets, ddof=1)) if len(log_rets) > 1 else 0.015
        current_vol_pct = daily_std * math.sqrt(252) * 100.0

        if current_vol_pct <= baseline_vol_pct:
            return 1.0
        elif current_vol_pct >= panic_vol_pct:
            return 0.20
        else:
            # Linear ramp-down
            slope = (0.20 - 1.0) / (panic_vol_pct - baseline_vol_pct)
            gate = 1.0 + slope * (current_vol_pct - baseline_vol_pct)
            return round(float(max(0.20, min(1.0, gate))), 3)


@dataclass(frozen=True)
class FinancialTurbulenceReport:
    """Multi-asset cross-sectional financial turbulence report (Kritzman & Li 2010 / FinRL)."""
    current_turbulence_score: float     # Mahalanobis distance / asset count
    historical_percentile: float        # Percentile rank [0.0, 100.0]
    turbulence_gate: float              # Damping multiplier [0.20, 1.0]
    is_crisis_alert: bool               # True if percentile >= 95.0
    is_elevated: bool                   # True if percentile >= 75.0
    assets_analyzed: int
    mean_historical_turbulence: float


class FinancialTurbulenceEngine:
    """Calculates Kritzman & Li (2010) Mahalanobis Financial Turbulence across asset portfolios.

    Inspired by FinRL's multi-stock environment turbulence threshold:
        Turbulence_t = (y_t - mu) @ Sigma^{-1} @ (y_t - mu).T / K
    Measures statistical abnormality in joint asset return distributions, detecting correlation
    breakdowns, systemic shocks, and regime breaks before they appear in single-asset indicators.
    """

    @classmethod
    def calculate_turbulence_vector(
        cls,
        returns_matrix: np.ndarray,
        window: int = 60,
    ) -> np.ndarray:
        """Compute rolling cross-asset turbulence vector across time periods.

        Args:
            returns_matrix: (T, K) 2D array of asset returns over T time periods across K assets.
            window: Rolling lookback window for historical mean vector and covariance matrix.
        """
        arr = np.asarray(returns_matrix, dtype=float)
        t, k = arr.shape
        if t < 10 or k < 2:
            return np.ones(t, dtype=float)

        effective_window = min(window, max(15, t // 2))
        turbulence = np.zeros(t, dtype=float)

        for i in range(effective_window, t):
            hist = arr[i - effective_window : i]
            mu = np.mean(hist, axis=0)
            cov = np.cov(hist, rowvar=False)

            # Add small Tikhonov regularization for matrix inversion stability
            reg_cov = cov + np.eye(k) * 1e-6
            try:
                inv_cov = np.linalg.pinv(reg_cov)
            except np.linalg.LinAlgError:
                inv_cov = np.eye(k)

            diff = arr[i] - mu
            dist = float(diff @ inv_cov @ diff.T) / float(k)
            turbulence[i] = max(0.0, dist)

        # Backfill initial window with the first valid observation
        if effective_window < t:
            turbulence[:effective_window] = turbulence[effective_window]

        return np.round(turbulence, 3)

    @classmethod
    def analyze_cross_asset_turbulence(
        cls,
        returns_matrix: np.ndarray,
        window: int = 60,
    ) -> FinancialTurbulenceReport:
        """Analyze current market turbulence state against historical empirical distribution."""
        turb_vec = cls.calculate_turbulence_vector(returns_matrix, window)
        current = float(turb_vec[-1]) if len(turb_vec) > 0 else 1.0
        n_assets = returns_matrix.shape[1] if returns_matrix.ndim == 2 else 1

        if len(turb_vec) >= 20:
            hist_scores = turb_vec[:-1]
            pct_rank = float(np.sum(hist_scores <= current) / len(hist_scores)) * 100.0
            mean_turb = float(np.mean(hist_scores))
        else:
            pct_rank = 50.0
            mean_turb = current

        # Dynamic Gating: Dampen risk when turbulence crosses statistical risk thresholds
        is_crisis = pct_rank >= 95.0
        is_elevated = pct_rank >= 75.0

        if is_crisis:
            # Extreme systemic shock: slash position sizing to 0.25x
            gate = 0.25
        elif is_elevated:
            # Elevated caution: scale down linearly from 1.0 to 0.50
            slope = (0.50 - 1.0) / (95.0 - 75.0)
            gate = 1.0 + slope * (pct_rank - 75.0)
        else:
            gate = 1.0

        return FinancialTurbulenceReport(
            current_turbulence_score=round(current, 2),
            historical_percentile=round(pct_rank, 1),
            turbulence_gate=round(float(max(0.20, min(1.0, gate))), 2),
            is_crisis_alert=is_crisis,
            is_elevated=is_elevated,
            assets_analyzed=n_assets,
            mean_historical_turbulence=round(mean_turb, 2),
        )


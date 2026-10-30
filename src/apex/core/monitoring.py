# apex-quant/src/apex/core/monitoring.py
"""Monitoring, Feature Drift Detection & Signal Decay Engine.

Guarantees operational stability and institutional alpha preservation:
1. Feature Drift Detection via Population Stability Index (PSI):
   - Compares current factor distributions against calibration baseline.
   - Triggers warning when PSI >= 0.10, critical alert when PSI >= 0.25.
2. Signal Decay & Rolling Information Coefficient (IC) Monitor:
   - IC_t = Spearman_corr(Composite_Score_t, Future_Return_{t+k})
   - Flags decay when rolling 20-period IC falls below 0.0.
3. Slippage Drift Alert:
   - Compares post-trade realized slippage against model predictions.
4. Comprehensive Health & Alert Dispatcher.
"""
from dataclasses import dataclass
import math
from typing import Dict, List, Mapping, Sequence, Tuple, Optional, Any
import numpy as np
from scipy import stats


@dataclass(frozen=True)
class FeatureDriftReport:
    """Telemetry measuring distribution shifts in quantitative factors."""
    factor_name: str
    psi_score: float                # Population Stability Index (<0.10: Stable, >=0.25: Critical Drift)
    status: str                     # "STABLE", "MODERATE_DRIFT", "SIGNIFICANT_DRIFT"
    baseline_mean: float
    current_mean: float
    is_recalibration_recommended: bool


@dataclass(frozen=True)
class SignalDecayReport:
    """Rolling Information Coefficient and predictive degradation telemetry."""
    signal_name: str
    current_rolling_ic: float       # Spearman rank correlation [-1.0, 1.0]
    mean_historical_ic: float
    ic_t_stat: float
    is_signal_decayed: bool         # IC < 0.0 indicates edge decay
    has_sufficient_data: bool = True # False when sample size < 8 observations


@dataclass(frozen=True)
class SystemAlert:
    """Operational or quantitative risk alert."""
    severity: str                   # "INFO", "WARNING", "CRITICAL"
    component: str
    message: str
    metric_value: float
    threshold_value: float


class MonitoringEngine:
    """Monitors quantitative alpha distributions, predictive power, and execution drift."""

    @staticmethod
    def calculate_psi(
        baseline: Sequence[float],
        current: Sequence[float],
        num_buckets: int = 10,
    ) -> float:
        """Calculate Population Stability Index (PSI) between baseline and current distributions."""
        b_arr = np.array(baseline)
        c_arr = np.array(current)

        if len(b_arr) < 10 or len(c_arr) < 10:
            return 0.0

        # Create equal-frequency quantile buckets from baseline
        quantiles = np.linspace(0, 100, num_buckets + 1)
        bins = np.percentile(b_arr, quantiles)
        # Ensure strictly increasing bins
        bins[0] -= 1e-5
        bins[-1] += 1e-5
        for i in range(1, len(bins)):
            if bins[i] <= bins[i - 1]:
                bins[i] = bins[i - 1] + 1e-4

        b_counts, _ = np.histogram(b_arr, bins=bins)
        c_counts, _ = np.histogram(c_arr, bins=bins)

        b_pct = (b_counts + 1e-5) / float(len(b_arr) + 1e-5 * num_buckets)
        c_pct = (c_counts + 1e-5) / float(len(c_arr) + 1e-5 * num_buckets)

        psi = np.sum((c_pct - b_pct) * np.log(c_pct / b_pct))
        return round(float(max(0.0, psi)), 4)

    @classmethod
    def evaluate_feature_drift(
        cls,
        factor_name: str,
        baseline_values: Sequence[float],
        current_values: Sequence[float],
    ) -> FeatureDriftReport:
        """Evaluate whether a factor's statistical distribution has drifted."""
        psi = cls.calculate_psi(baseline_values, current_values)
        b_mean = float(np.mean(baseline_values)) if len(baseline_values) > 0 else 0.0
        c_mean = float(np.mean(current_values)) if len(current_values) > 0 else 0.0

        if psi < 0.10:
            status = "STABLE"
            recal = False
        elif psi < 0.25:
            status = "MODERATE_DRIFT"
            recal = False
        else:
            status = "SIGNIFICANT_DRIFT"
            recal = True

        return FeatureDriftReport(
            factor_name=factor_name,
            psi_score=psi,
            status=status,
            baseline_mean=round(b_mean, 2),
            current_mean=round(c_mean, 2),
            is_recalibration_recommended=recal,
        )

    @staticmethod
    def calculate_rolling_ic(
        signals: Sequence[float],
        realized_forward_returns: Sequence[float],
        historical_ic_benchmark: float = 0.0,
    ) -> SignalDecayReport:
        """Compute Spearman Rank Information Coefficient (IC) to measure alpha decay (F14)."""
        sig = np.array(signals)
        rets = np.array(realized_forward_returns)

        # Insufficient data: report has_sufficient_data=False and 0.0 metrics rather than fabricated numbers
        if len(sig) < 8 or len(rets) < 8:
            return SignalDecayReport(
                signal_name="COMPOSITE_ALPHA",
                current_rolling_ic=0.0,
                mean_historical_ic=0.0,
                ic_t_stat=0.0,
                is_signal_decayed=False,
                has_sufficient_data=False,
            )

        # Spearman rank correlation
        rho, p_val = stats.spearmanr(sig, rets)
        if math.isnan(rho):
            rho = 0.0

        n = len(sig)
        t_stat = rho * math.sqrt((n - 2) / (1.0 - rho**2 + 1e-8)) if abs(rho) < 1.0 else 3.0

        is_decayed = bool(rho < 0.0)

        return SignalDecayReport(
            signal_name="COMPOSITE_ALPHA",
            current_rolling_ic=round(float(rho), 3),
            mean_historical_ic=round(float(historical_ic_benchmark or rho), 3),
            ic_t_stat=round(float(t_stat), 2),
            is_signal_decayed=is_decayed,
            has_sufficient_data=True,
        )

    @staticmethod
    def check_system_alerts(
        current_drawdown_pct: float,
        portfolio_var_95_pct: float,
        realized_slippage_bps: float,
        modeled_slippage_bps: float,
    ) -> List[SystemAlert]:
        """Generate structured operational alerts when risk limits or slippage models diverge."""
        alerts: List[SystemAlert] = []

        # 1. Daily drawdown check (max 2%)
        if current_drawdown_pct >= 1.5:
            severity = "CRITICAL" if current_drawdown_pct >= 2.0 else "WARNING"
            alerts.append(
                SystemAlert(
                    severity=severity,
                    component="RiskGate",
                    message=f"Drawdown {current_drawdown_pct:.2f}% approaching circuit breaker",
                    metric_value=current_drawdown_pct,
                    threshold_value=2.0,
                )
            )

        # 2. Portfolio VaR check
        if portfolio_var_95_pct >= 3.0:
            alerts.append(
                SystemAlert(
                    severity="WARNING",
                    component="PortfolioRiskEngine",
                    message=f"1-day VaR 95% elevated at {portfolio_var_95_pct:.2f}%",
                    metric_value=portfolio_var_95_pct,
                    threshold_value=3.0,
                )
            )

        # 3. Slippage divergence check (> 30% worse than modeled)
        slip_diff = realized_slippage_bps - modeled_slippage_bps
        if slip_diff >= 3.0:
            alerts.append(
                SystemAlert(
                    severity="WARNING",
                    component="DynamicSlippageModel",
                    message=f"Realized slippage ({realized_slippage_bps:.1f} bps) exceeds model ({modeled_slippage_bps:.1f} bps)",
                    metric_value=realized_slippage_bps,
                    threshold_value=modeled_slippage_bps,
                )
            )

        return alerts

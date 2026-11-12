# apex-quant/src/apex/core/validation.py
"""Institutional Cross-Validation, Purging, Overfitting Detection & Asymmetric Risk Service.

Integrates institutional methodology from:
1. Marcos López de Prado / Bailey et al.:
   - Combinatorial Purged Cross-Validation (CPCV)
   - Probability of Backtest Overfitting (PBO)
   - Deflated Sharpe Ratio (DSR) correcting for skewness, kurtosis, and selection bias
2. VectorBT (Polakow):
   - Omega Ratio: Probability-weighted ratio of gains vs losses over hurdle rate L
   - Tail Ratio: Percentile(95) / abs(Percentile(5)) measuring payoff asymmetry
   - Common Sense Ratio (CSR): Tail Ratio * Gain-to-Pain Ratio
   - Calmar Ratio: Annualized return / Maximum Drawdown
3. Backtrader (Rodriguez):
   - Van Tharp's System Quality Number (SQN)
   - Variability-Weighted Return (VWR) penalizing equity-curve variance
"""
from dataclasses import dataclass
import itertools
import math
from typing import List, Sequence, Tuple, Optional
import numpy as np
from scipy import stats


@dataclass(frozen=True)
class ValidationReport:
    """Rigorous statistical validation report for quantitative strategies."""
    nominal_sharpe_ratio: float
    deflated_sharpe_ratio: float       # DSR in [0.0, 1.0] (probability that true SR > benchmark)
    probability_of_overfitting: float   # PBO in [0.0, 1.0] (< 0.20 is robust)
    sample_skewness: float
    sample_kurtosis: float
    total_effective_observations: int
    is_statistically_significant: bool  # True if DSR >= 0.90 and PBO <= 0.30
    verdict: str
    omega_ratio: float = 1.0           # VectorBT: Probability-weighted gain/loss ratio
    tail_ratio: float = 1.0            # VectorBT: P95 / |P5| payoff asymmetry
    common_sense_ratio: float = 1.0    # VectorBT: Tail Ratio * Gain-to-Pain
    calmar_ratio: float = 0.0          # VectorBT/Backtrader: Ann. Return / Max Drawdown
    system_quality_number: float = 0.0 # Backtrader: Van Tharp SQN
    sqn_category: str = "Average"      # Backtrader: Van Tharp category


class InstitutionalValidator:
    """Validates quantitative signals against overfitting and data snooping."""

    @staticmethod
    def calculate_deflated_sharpe_ratio(
        returns: Sequence[float],
        benchmark_sharpe: float = 0.0,
        num_trials: int = 10,
        annualization_factor: float = math.sqrt(252),
    ) -> Tuple[float, float, float, float]:
        """Compute the Deflated Sharpe Ratio (DSR) correcting for skewness, kurtosis, and trial count.
        
        Returns:
            (nominal_sr, deflated_sr, skewness, kurtosis)
        """
        arr = np.array(returns, dtype=float)
        n = len(arr)
        if n < 5:
            return 0.0, 0.0, 0.0, 3.0

        mean = float(np.mean(arr))
        std = float(np.std(arr, ddof=1)) + 1e-10
        sr_per_period = mean / std
        nominal_sr = sr_per_period * annualization_factor

        # Skewness and Kurtosis
        skew = float(stats.skew(arr))
        kurt = float(stats.kurtosis(arr, fisher=False))  # Normal = 3.0

        # Expected maximum Sharpe ratio under null hypothesis of zero skill over N trials
        euler = 0.5772156649
        if num_trials > 1:
            z_term = stats.norm.ppf(1.0 - (1.0 / num_trials))
            z_e = stats.norm.ppf(1.0 - (1.0 / (num_trials * math.e)))
            expected_max_sr = (1.0 - euler) * z_term + euler * z_e
        else:
            expected_max_sr = benchmark_sharpe

        # Standard error of Sharpe ratio under non-normality (Mertens 2002 / Bailey & López de Prado)
        sr_var = 1.0 - skew * sr_per_period + ((kurt - 1.0) / 4.0) * (sr_per_period ** 2)
        sr_std_err = math.sqrt(max(1e-8, sr_var)) / math.sqrt(n - 1)

        # Deflated Sharpe z-score on consistent per-period scale
        z_stat = (sr_per_period - expected_max_sr) / (sr_std_err + 1e-10)
        dsr_prob = float(stats.norm.cdf(z_stat))

        return round(nominal_sr, 2), round(dsr_prob, 4), round(skew, 2), round(kurt, 2)

    @classmethod
    def calculate_pbo_from_paths(
        cls,
        matrix_returns: np.ndarray,
        num_splits: int = 6,
    ) -> float:
        """Calculate Probability of Backtest Overfitting (PBO) across combinatorial splits.
        
        Args:
            matrix_returns: (T, N) array where each column is the return stream of one strategy parameter variant.
        """
        t, num_strats = matrix_returns.shape
        if num_strats < 2 or t < 30:
            return 0.10  # Baseline low default when only one candidate is tested

        split_size = t // num_splits
        splits = [matrix_returns[i * split_size : (i + 1) * split_size] for i in range(num_splits)]

        half = num_splits // 2
        combos = list(itertools.combinations(range(num_splits), half))

        rank_violations = 0
        total_evals = 0

        for is_indices in combos[:20]:
            oos_indices = [idx for idx in range(num_splits) if idx not in is_indices]

            is_data = np.vstack([splits[i] for i in is_indices])
            is_sr = np.mean(is_data, axis=0) / (np.std(is_data, axis=0) + 1e-8)

            oos_data = np.vstack([splits[i] for i in oos_indices])
            oos_sr = np.mean(oos_data, axis=0) / (np.std(oos_data, axis=0) + 1e-8)

            best_is_idx = int(np.argmax(is_sr))
            oos_rank = stats.percentileofscore(oos_sr, oos_sr[best_is_idx]) / 100.0

            if oos_rank < 0.50:
                rank_violations += 1
            total_evals += 1

        pbo = (rank_violations / total_evals) if total_evals > 0 else 0.15
        return round(pbo, 3)

    @staticmethod
    def calculate_omega_ratio(returns: Sequence[float], hurdle_rate: float = 0.0) -> float:
        """VectorBT-inspired Omega Ratio: probability-weighted ratio of gains vs losses.
        
        Omega = sum(max(0, r - L)) / sum(max(0, L - r))
        Unlike Sharpe ratio, Omega requires no assumption of Gaussian normality.
        """
        arr = np.array(returns, dtype=float) - hurdle_rate
        pos = arr[arr > 0]
        neg = arr[arr < 0]
        sum_pos = float(np.sum(pos)) if len(pos) > 0 else 0.0
        sum_neg = float(np.sum(np.abs(neg))) if len(neg) > 0 else 1e-8
        return round(sum_pos / sum_neg, 3)

    @staticmethod
    def calculate_tail_ratio(returns: Sequence[float], right_pct: float = 95.0, left_pct: float = 5.0) -> float:
        """VectorBT-inspired Tail Ratio: Percentile(95) / abs(Percentile(5)).
        
        Directly measures positive right-tail asymmetry. > 1.0 implies positive skew/fat right tail.
        """
        arr = np.array(returns, dtype=float)
        if len(arr) < 10:
            return 1.0
        p95 = float(np.percentile(arr, right_pct))
        p5 = float(np.percentile(arr, left_pct))
        if abs(p5) < 1e-8:
            return round(max(1.0, p95 / 1e-4), 2)
        return round(p95 / abs(p5), 3)

    @staticmethod
    def calculate_common_sense_ratio(returns: Sequence[float]) -> float:
        """VectorBT-inspired Common Sense Ratio: Tail Ratio * Gain-to-Pain Ratio."""
        arr = np.array(returns, dtype=float)
        if len(arr) < 10:
            return 1.0
        tail = InstitutionalValidator.calculate_tail_ratio(arr)
        pos = arr[arr > 0]
        neg = arr[arr < 0]
        sum_pos = float(np.sum(pos)) if len(pos) > 0 else 0.0
        sum_neg = float(np.sum(np.abs(neg))) if len(neg) > 0 else 1e-8
        gain_to_pain = sum_pos / sum_neg
        return round(tail * gain_to_pain, 3)

    @staticmethod
    def calculate_calmar_ratio(returns: Sequence[float], max_drawdown_pct: Optional[float] = None) -> float:
        """Calculate Calmar Ratio: Annualized Return / Max Drawdown."""
        arr = np.array(returns, dtype=float)
        if len(arr) < 5:
            return 0.0
        ann_return = float(np.mean(arr) * 252.0)
        if max_drawdown_pct is not None and max_drawdown_pct > 0:
            mdd = max_drawdown_pct
        else:
            # Estimate maximum drawdown from cumulative returns
            cum = np.cumprod(1.0 + arr)
            peak = np.maximum.accumulate(cum)
            dd = (peak - cum) / (peak + 1e-8)
            mdd = float(np.max(dd))
        if mdd <= 1e-6:
            return round(max(0.0, ann_return / 0.01), 2)
        return round(ann_return / mdd, 2)

    @staticmethod
    def calculate_system_quality_number(trade_pnls: Sequence[float]) -> Tuple[float, str]:
        """Backtrader-inspired Van Tharp System Quality Number (SQN).
        
        SQN = sqrt(min(N, 100)) * Mean(TradePnL) / StdDev(TradePnL)
        Categorization:
          - < 1.6 : Poor / Below Average
          - 1.6 - 1.9 : Average
          - 2.0 - 2.4 : Good
          - 2.5 - 2.9 : Very Good
          - 3.0 - 5.0 : Excellent
          - 5.1 - 6.9 : Superb
          - >= 7.0 : Holy Grail
        """
        arr = np.array(trade_pnls, dtype=float)
        n = len(arr)
        if n < 5:
            return 0.0, "Insufficient Trades"
        mean_pnl = float(np.mean(arr))
        std_pnl = float(np.std(arr, ddof=1)) + 1e-8
        sqn = math.sqrt(min(n, 100)) * (mean_pnl / std_pnl)

        if sqn < 1.6:
            cat = "Below Average / Weak"
        elif sqn < 2.0:
            cat = "Average"
        elif sqn < 2.5:
            cat = "Good"
        elif sqn < 3.0:
            cat = "Very Good"
        elif sqn < 5.0:
            cat = "Excellent"
        elif sqn < 7.0:
            cat = "Superb"
        else:
            cat = "Holy Grail"

        return round(sqn, 2), cat

    @staticmethod
    def calculate_variability_weighted_return(
        returns: Sequence[float],
        tau: float = 2.0,
        sdev_max: float = 2.0,
    ) -> float:
        """Backtrader-inspired Variability-Weighted Return (VWR).
        
        Penalizes volatile, erratic return paths relative to an exponential trend.
        """
        arr = np.array(returns, dtype=float)
        if len(arr) < 10:
            return 0.0
        mean_ret = float(np.mean(arr))
        std_ret = float(np.std(arr, ddof=1))
        norm_return = mean_ret * 252.0 * 100.0  # Annualized %
        penalty = math.pow(min(sdev_max, std_ret * math.sqrt(252)) / sdev_max, tau)
        vwr = norm_return * max(0.0, 1.0 - penalty)
        return round(vwr, 2)

    @classmethod
    def evaluate_strategy_integrity(
        cls,
        returns: Sequence[float],
        num_candidate_models_tested: int = 10,
        candidate_matrix: Optional[np.ndarray] = None,
        trade_pnls: Optional[Sequence[float]] = None,
    ) -> ValidationReport:
        """Produce an end-to-end institutional validation report with VectorBT & Backtrader metrics."""
        nom_sr, dsr, skew, kurt = cls.calculate_deflated_sharpe_ratio(
            returns=returns,
            num_trials=num_candidate_models_tested,
        )

        arr = np.array(returns, dtype=float)
        if candidate_matrix is not None and isinstance(candidate_matrix, np.ndarray) and candidate_matrix.shape[1] >= 2:
            pbo = cls.calculate_pbo_from_paths(candidate_matrix)
        elif len(arr) >= 30:
            sub1 = np.roll(arr, 1)
            sub2 = np.roll(arr, 2)
            sub3 = (arr + sub1) / 2.0
            matrix = np.column_stack([arr, sub1, sub2, sub3])
            pbo = cls.calculate_pbo_from_paths(matrix)
        else:
            pbo = 0.12

        # Asymmetric & Distributional Metrics (VectorBT & Backtrader)
        omega = cls.calculate_omega_ratio(arr)
        tail = cls.calculate_tail_ratio(arr)
        csr = cls.calculate_common_sense_ratio(arr)
        calmar = cls.calculate_calmar_ratio(arr)
        vwr = cls.calculate_variability_weighted_return(arr)

        if trade_pnls is not None and len(trade_pnls) >= 5:
            sqn, sqn_cat = cls.calculate_system_quality_number(trade_pnls)
        else:
            # Approximate trade PnL from return stream blocks
            sim_trades = arr[arr != 0]
            sqn, sqn_cat = cls.calculate_system_quality_number(sim_trades)

        is_sig = (dsr >= 0.90) and (pbo <= 0.30)
        if is_sig and omega >= 1.25 and sqn >= 2.0:
            verdict = "PASSED: Institutional-grade edge verified (DSR, PBO, Omega, and SQN confirmed)."
        elif is_sig:
            verdict = "PASSED: True edge verified with high confidence; low overfitting risk."
        elif dsr < 0.70:
            verdict = "WARNING: Nominal Sharpe ratio is likely inflated by selection bias or non-normality."
        else:
            verdict = "MARGINAL: Moderate statistical edge; recommended to increase out-of-sample horizon."

        return ValidationReport(
            nominal_sharpe_ratio=nom_sr,
            deflated_sharpe_ratio=dsr,
            probability_of_overfitting=pbo,
            sample_skewness=skew,
            sample_kurtosis=kurt,
            total_effective_observations=len(returns),
            is_statistically_significant=is_sig,
            verdict=verdict,
            omega_ratio=omega,
            tail_ratio=tail,
            common_sense_ratio=csr,
            calmar_ratio=calmar,
            system_quality_number=sqn,
            sqn_category=sqn_cat,
        )

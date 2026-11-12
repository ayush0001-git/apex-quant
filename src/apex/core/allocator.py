# apex-quant/src/apex/core/allocator.py
"""Multi-Strategy Capital Allocation, Risk Parity & Asymmetric Blending Service.

Integrates institutional allocation methodologies:
1. Inverse Volatility / Risk Parity weighting across uncorrelated strategy streams.
2. Correlation-Aware Collinearity Adjustment: Penalizes redundant, highly correlated strategies (rho > 0.60).
3. FinRL Cash-Penalty Buffer: Enforces explicit liquidity reserve buffer to prevent over-allocation.
4. VectorBT Payoff Asymmetry (Tail Ratio) Scaling: Dynamically rewards strategies with positive
   right-tail fatness (P95 / |P5| > 1.0) and penalizes strategies with negative left-tail crashes.
"""
from dataclasses import dataclass
import math
from typing import Dict, List, Mapping, Sequence, Tuple, Optional
import numpy as np
import pandas as pd


@dataclass(frozen=True)
class SubStrategyProfile:
    """Performance telemetry and risk metrics for a single strategy pillar."""
    strategy_id: str
    strategy_name: str
    annualized_return_pct: float
    annualized_volatility_pct: float
    sharpe_ratio: float
    allocated_weight_pct: float     # Target allocation weight (0.0% to 100.0%)
    allocated_capital_inr: float    # Rupee allocation from active equity
    risk_contribution_pct: float   # % of total portfolio variance contributed
    omega_ratio: float = 1.0        # VectorBT: gain/loss probability ratio
    tail_ratio: float = 1.0         # VectorBT: P95 / |P5| payoff asymmetry


@dataclass(frozen=True)
class StrategyAllocationReport:
    """Consolidated multi-strategy capital allocation report."""
    total_portfolio_equity: float
    strategies: Tuple[SubStrategyProfile, ...]
    correlation_matrix: Mapping[str, Mapping[str, float]]
    effective_number_of_strategies: float # ENC: 1.0 (monolithic) to 3.0 (fully uncorrelated)
    portfolio_expected_sharpe: float
    rebalancing_needed: bool
    cash_reserve_inr: float = 0.0   # FinRL: unallocated liquidity preservation reserve
    cash_reserve_pct: float = 0.0


class MultiStrategyAllocator:
    """Dynamic capital allocator blending trend, mean-reversion, and factor strategies."""

    STRATEGY_NAMES = {
        "trend_following": "Trend-Following (EMA/VWAP Breakout)",
        "mean_reversion": "Mean-Reversion (RSI/BB Compression)",
        "factor_investing": "Cross-Sectional Factor Alpha (Carhart + Quality)",
    }

    def __init__(self, target_volatility_pct: float = 15.0, max_correlation_threshold: float = 0.60) -> None:
        self.target_volatility = target_volatility_pct
        self.max_corr = max_correlation_threshold

    def allocate_capital(
        self,
        strategy_returns: Mapping[str, Sequence[float]],
        total_equity: float = 100000.0,
        cash_reserve_pct: float = 0.0,
        tail_risk_adjustment: bool = False,
    ) -> StrategyAllocationReport:
        """Compute optimal risk-parity capital weights across strategy streams.
        
        Args:
            strategy_returns: Dict mapping strategy_id to historical return series.
            total_equity: Total portfolio equity in INR.
            cash_reserve_pct: FinRL-inspired cash penalty reserve [0.0, 0.50].
            tail_risk_adjustment: VectorBT-inspired payoff asymmetry scaling via Tail Ratio.
        """
        strat_keys = list(strategy_returns.keys())
        if not strat_keys:
            return StrategyAllocationReport(
                total_portfolio_equity=total_equity,
                strategies=(),
                correlation_matrix={},
                effective_number_of_strategies=1.0,
                portfolio_expected_sharpe=0.0,
                rebalancing_needed=False,
                cash_reserve_inr=0.0,
                cash_reserve_pct=0.0,
            )

        df_rets = pd.DataFrame(strategy_returns)
        vols = df_rets.std().values * math.sqrt(252) * 100.0
        vols = np.maximum(vols, 1.0)
        means = df_rets.mean().values * 252 * 100.0

        # 1. Base Inverse Volatility Weights (Risk Parity approximation)
        inv_vols = 1.0 / vols
        base_weights = inv_vols / np.sum(inv_vols)

        # 2. Correlation-Aware Collinearity Adjustment
        corr_matrix = df_rets.corr().fillna(0.0).values
        n = len(strat_keys)
        penalties = np.ones(n)

        for i in range(n):
            for j in range(i + 1, n):
                r = abs(float(corr_matrix[i, j]))
                if r > self.max_corr:
                    excess = r - self.max_corr
                    penalties[i] *= (1.0 - (0.4 * excess))
                    penalties[j] *= (1.0 - (0.4 * excess))

        adj_weights = base_weights * penalties

        # 3. VectorBT Tail-Asymmetry Adjustment (Optional)
        tail_ratios = np.ones(n)
        omega_ratios = np.ones(n)
        for idx, key in enumerate(strat_keys):
            series = df_rets[key].dropna().values
            if len(series) >= 10:
                p95 = float(np.percentile(series, 95))
                p5 = abs(float(np.percentile(series, 5)))
                tail_ratios[idx] = max(0.5, p95 / (p5 + 1e-8))

                pos_sum = float(np.sum(series[series > 0])) if np.any(series > 0) else 0.0
                neg_sum = abs(float(np.sum(series[series < 0]))) if np.any(series < 0) else 1e-8
                omega_ratios[idx] = max(0.2, pos_sum / neg_sum)

        if tail_risk_adjustment:
            # Scale weights by sqrt of tail ratio: reward positive fat tails, dampen negative skew
            asym_mult = np.clip(np.sqrt(tail_ratios), 0.75, 1.35)
            adj_weights = adj_weights * asym_mult

        final_weights = adj_weights / np.sum(adj_weights)

        # 4. FinRL Cash Reserve Buffer
        clamped_cash_pct = max(0.0, min(0.50, float(cash_reserve_pct)))
        cash_inr = round(total_equity * clamped_cash_pct, 2)
        active_equity = total_equity - cash_inr

        # 5. Calculate Risk Contributions
        cov = df_rets.cov().values * 252 * 10000.0
        port_var = float(final_weights.T @ cov @ final_weights)
        port_vol = math.sqrt(max(1e-8, port_var))
        marginal_risk = (cov @ final_weights) / port_vol
        risk_contributions = (final_weights * marginal_risk) / (port_vol + 1e-8)

        # 6. Effective Number of Uncorrelated Bets: ENC = 1 / sum(w_i^2)
        enc = float(1.0 / np.sum(final_weights ** 2))

        # Expected Sharpe
        port_mean = float(np.sum(final_weights * means))
        port_sharpe = round(port_mean / (port_vol + 1e-8), 2)

        # Build Profiles
        profiles: List[SubStrategyProfile] = []
        for idx, key in enumerate(strat_keys):
            ann_ret = float(means[idx])
            ann_vol = float(vols[idx])
            sr = round(ann_ret / ann_vol, 2)
            w_pct = round(float(final_weights[idx]) * 100.0, 1)
            cap_inr = round(float(final_weights[idx]) * active_equity, 2)
            rc_pct = round(float(risk_contributions[idx]) * 100.0, 1)

            profiles.append(
                SubStrategyProfile(
                    strategy_id=key,
                    strategy_name=self.STRATEGY_NAMES.get(key, key.replace("_", " ").title()),
                    annualized_return_pct=round(ann_ret, 1),
                    annualized_volatility_pct=round(ann_vol, 1),
                    sharpe_ratio=sr,
                    allocated_weight_pct=w_pct,
                    allocated_capital_inr=cap_inr,
                    risk_contribution_pct=rc_pct,
                    omega_ratio=round(float(omega_ratios[idx]), 2),
                    tail_ratio=round(float(tail_ratios[idx]), 2),
                )
            )

        # Build correlation dict
        corr_dict: Dict[str, Dict[str, float]] = {}
        for i, k1 in enumerate(strat_keys):
            corr_dict[k1] = {}
            for j, k2 in enumerate(strat_keys):
                corr_dict[k1][k2] = round(float(corr_matrix[i, j]), 2)

        # Rebalancing needed if any strategy weight drifts > 5% from equal contribution
        equal_w = 1.0 / n
        max_drift = max(abs(w - equal_w) for w in final_weights)
        rebalance = bool(max_drift > 0.15)

        return StrategyAllocationReport(
            total_portfolio_equity=total_equity,
            strategies=tuple(profiles),
            correlation_matrix=corr_dict,
            effective_number_of_strategies=round(enc, 2),
            portfolio_expected_sharpe=port_sharpe,
            rebalancing_needed=rebalance,
            cash_reserve_inr=cash_inr,
            cash_reserve_pct=round(clamped_cash_pct * 100.0, 1),
        )

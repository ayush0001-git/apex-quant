# apex-quant/src/apex/core/allocator.py
"""Multi-Strategy Capital Allocation & Strategy Blender.

Implements institutional portfolio construction across uncorrelated alpha streams:
1. Trend-Following Sub-Strategy (EMA/VWAP Trend Expansion, High Confluence)
2. Mean-Reversion Sub-Strategy (RSI / Bollinger Band Reversals in Range Compression)
3. Cross-Sectional Factor Sub-Strategy (Carhart Momentum + Quality + Low-Volatility Tilt)

Allocation Methodology:
- Risk Parity / Inverse Volatility weighting: w_i ~ 1 / sigma_i
- Correlation-Aware Collinearity Penalty: Dampens weights when strategy return streams
  become collinear (rho > 0.60), enforcing true statistical diversification.
- Evaluates Effective Number of Uncorrelated Bets (ENC / Diversification Ratio).
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
    allocated_capital_inr: float    # Rupee allocation from total equity
    risk_contribution_pct: float   # % of total portfolio variance contributed


@dataclass(frozen=True)
class StrategyAllocationReport:
    """Consolidated multi-strategy capital allocation report."""
    total_portfolio_equity: float
    strategies: Tuple[SubStrategyProfile, ...]
    correlation_matrix: Mapping[str, Mapping[str, float]]
    effective_number_of_strategies: float # ENC: 1.0 (monolithic) to 3.0 (fully uncorrelated)
    portfolio_expected_sharpe: float
    rebalancing_needed: bool


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
    ) -> StrategyAllocationReport:
        """Compute optimal risk-parity capital weights across strategy streams."""
        strat_keys = list(strategy_returns.keys())
        if not strat_keys:
            return StrategyAllocationReport(
                total_portfolio_equity=total_equity,
                strategies=(),
                correlation_matrix={},
                effective_number_of_strategies=1.0,
                portfolio_expected_sharpe=0.0,
                rebalancing_needed=False,
            )

        df_rets = pd.DataFrame(strategy_returns)
        vols = df_rets.std().values * math.sqrt(252) * 100.0
        # Prevent zero-division
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
                    # Apply penalty to redundant strategies
                    excess = r - self.max_corr
                    penalties[i] *= (1.0 - (0.4 * excess))
                    penalties[j] *= (1.0 - (0.4 * excess))

        adj_weights = base_weights * penalties
        final_weights = adj_weights / np.sum(adj_weights)

        # 3. Calculate Risk Contributions
        cov = df_rets.cov().values * 252 * 10000.0
        port_var = float(final_weights.T @ cov @ final_weights)
        port_vol = math.sqrt(max(1e-8, port_var))
        marginal_risk = (cov @ final_weights) / port_vol
        risk_contributions = (final_weights * marginal_risk) / (port_vol + 1e-8)

        # 4. Effective Number of Uncorrelated Bets: ENC = 1 / sum(w_i^2)
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
            cap_inr = round(float(final_weights[idx]) * total_equity, 2)
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
                )
            )

        # Build correlation dict
        corr_dict: Dict[str, Dict[str, float]] = {}
        for i, k1 in enumerate(strat_keys):
            corr_dict[k1] = {}
            for j, k2 in enumerate(strat_keys):
                corr_dict[k1][k2] = round(float(corr_matrix[i, j]), 2)

        return StrategyAllocationReport(
            total_portfolio_equity=total_equity,
            strategies=tuple(profiles),
            correlation_matrix=corr_dict,
            effective_number_of_strategies=round(enc, 2),
            portfolio_expected_sharpe=port_sharpe,
            rebalancing_needed=enc >= 1.5,
        )

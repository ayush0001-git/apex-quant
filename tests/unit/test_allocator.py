# apex-quant/tests/unit/test_allocator.py
"""Unit tests for MultiStrategyAllocator (Risk Parity & Collinearity penalty)."""
import numpy as np
import pytest
from apex.core.allocator import MultiStrategyAllocator, StrategyAllocationReport


def test_multi_strategy_allocator_balances_weights():
    allocator = MultiStrategyAllocator()
    
    np.random.seed(42)
    # 3 strategies with varying volatility: Trend (vol=18%), Reversion (vol=10%), Factor (vol=12%)
    rets_trend = list(np.random.normal(0.001, 0.018, 100))
    rets_revert = list(np.random.normal(0.0008, 0.010, 100))
    rets_factor = list(np.random.normal(0.0009, 0.012, 100))
    
    strategy_returns = {
        "trend_following": rets_trend,
        "mean_reversion": rets_revert,
        "factor_investing": rets_factor,
    }
    
    report = allocator.allocate_capital(strategy_returns, total_equity=100000.0)
    
    assert isinstance(report, StrategyAllocationReport)
    assert len(report.strategies) == 3
    assert 99.0 <= sum(s.allocated_weight_pct for s in report.strategies) <= 101.0
    assert report.effective_number_of_strategies >= 2.0
    
    # Lower volatility strategy (mean_reversion) should receive higher weight than high vol trend_following
    revert_strat = next(s for s in report.strategies if s.strategy_id == "mean_reversion")
    trend_strat = next(s for s in report.strategies if s.strategy_id == "trend_following")
    assert revert_strat.allocated_weight_pct > trend_strat.allocated_weight_pct


def test_multi_strategy_allocator_penalizes_collinear_strategies():
    allocator = MultiStrategyAllocator(max_correlation_threshold=0.50)
    
    np.random.seed(42)
    base_signal = np.random.normal(0.001, 0.015, 100)
    # High correlation between strat1 and strat2 (0.95)
    s1 = list(base_signal)
    s2 = list(base_signal + np.random.normal(0.0, 0.003, 100))
    # Uncorrelated s3
    s3 = list(np.random.normal(0.001, 0.015, 100))
    
    report = allocator.allocate_capital({"s1": s1, "s2": s2, "s3": s3})
    
    # Uncorrelated s3 should get higher weight due to collinearity penalty on s1 & s2
    s3_profile = next(s for s in report.strategies if s.strategy_id == "s3")
    s1_profile = next(s for s in report.strategies if s.strategy_id == "s1")
    assert s3_profile.allocated_weight_pct > s1_profile.allocated_weight_pct

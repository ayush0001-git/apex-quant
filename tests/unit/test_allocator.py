# apex-quant/tests/unit/test_allocator.py
"""Unit tests for MultiStrategyAllocator (Risk Parity, Collinearity, FinRL Cash & VectorBT Tail Asymmetry)."""
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


def test_multi_strategy_allocator_finrl_cash_reserve():
    """Verify FinRL cash buffer carves out liquidity reserve before allocation."""
    allocator = MultiStrategyAllocator()
    s1 = list(np.random.normal(0.001, 0.01, 50))
    s2 = list(np.random.normal(0.001, 0.01, 50))
    
    report = allocator.allocate_capital(
        {"s1": s1, "s2": s2},
        total_equity=100000.0,
        cash_reserve_pct=0.15,
    )
    
    assert report.cash_reserve_inr == 15000.0
    assert report.cash_reserve_pct == 15.0
    # Allocated capital across strategies should sum to active equity (85,000)
    total_allocated = sum(s.allocated_capital_inr for s in report.strategies)
    assert 84900.0 <= total_allocated <= 85100.0


def test_multi_strategy_allocator_vectorbt_tail_asymmetry():
    """Verify VectorBT tail-asymmetry adjustment rewards positive right-tail payoffs."""
    allocator = MultiStrategyAllocator()
    np.random.seed(42)
    
    # Strat A: Positive asymmetric right tail (big winners, small losses)
    strat_a = list(np.concatenate([np.random.exponential(0.03, 60), -np.random.exponential(0.01, 40)]))
    # Strat B: Negative asymmetric left tail (small wins, big crash losses)
    strat_b = list(np.concatenate([np.random.exponential(0.01, 60), -np.random.exponential(0.03, 40)]))
    
    report_unadjusted = allocator.allocate_capital({"a": strat_a, "b": strat_b}, tail_risk_adjustment=False)
    report_adjusted = allocator.allocate_capital({"a": strat_a, "b": strat_b}, tail_risk_adjustment=True)
    
    a_unadj = next(s for s in report_unadjusted.strategies if s.strategy_id == "a").allocated_weight_pct
    a_adj = next(s for s in report_adjusted.strategies if s.strategy_id == "a").allocated_weight_pct
    
    # Positively asymmetric strategy A receives higher weight when tail risk adjustment is active
    assert a_adj > a_unadj

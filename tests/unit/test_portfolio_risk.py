# apex-quant/tests/unit/test_portfolio_risk.py
"""Unit tests for PortfolioRiskEngine (VaR, CVaR, Monte Carlo & Stress Testing)."""
import numpy as np
import pytest
from apex.core.portfolio_risk import PortfolioRiskEngine


def test_portfolio_risk_empty_positions():
    engine = PortfolioRiskEngine()
    report = engine.evaluate_portfolio(
        positions={},
        historical_returns={},
        total_equity=100000.0,
    )
    
    assert report.total_allocated_capital == 0.0
    assert report.cash_reserve_pct == 100.0
    assert report.portfolio_var_95_1d_pct == 0.0
    assert report.is_var_approved is True


def test_portfolio_risk_var_and_monte_carlo():
    engine = PortfolioRiskEngine(max_portfolio_var_pct=0.04, max_portfolio_cvar_pct=0.06)
    
    # 2 uncorrelated assets
    np.random.seed(42)
    rets_reliance = list(np.random.normal(0.001, 0.015, 50))
    rets_tcs = list(np.random.normal(0.0008, 0.012, 50))
    
    positions = {"RELIANCE.NS": 30000.0, "TCS.NS": 20000.0}
    returns = {"RELIANCE.NS": rets_reliance, "TCS.NS": rets_tcs}
    
    report = engine.evaluate_portfolio(
        positions=positions,
        historical_returns=returns,
        total_equity=100000.0,
    )
    
    assert report.total_allocated_capital == 50000.0
    assert report.cash_reserve_pct == 50.0
    assert report.portfolio_var_95_1d_pct > 0.0
    assert report.portfolio_cvar_95_pct >= report.portfolio_var_95_1d_pct
    assert len(report.stress_test_results) == 4
    assert report.is_var_approved is True


def test_portfolio_risk_correlation_rejection():
    # Tight correlation threshold (0.50)
    engine = PortfolioRiskEngine(max_asset_correlation=0.50)
    
    # 2 highly correlated assets (correlation = 0.98)
    np.random.seed(42)
    base = np.random.normal(0.0, 0.02, 40)
    rets_1 = list(base)
    rets_2 = list(base + np.random.normal(0.0, 0.002, 40))
    
    positions = {"HDFCBANK.NS": 25000.0, "ICICIBANK.NS": 25000.0}
    returns = {"HDFCBANK.NS": rets_1, "ICICIBANK.NS": rets_2}
    
    report = engine.evaluate_portfolio(
        positions=positions,
        historical_returns=returns,
        total_equity=100000.0,
    )
    
    assert report.max_pairwise_correlation > 0.85
    assert report.is_correlation_approved is False
    assert "High correlation" in report.rejection_reason


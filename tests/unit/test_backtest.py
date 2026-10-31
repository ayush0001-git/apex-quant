# apex-quant/tests/unit/test_backtest.py
"""Unit tests for the BacktestEngine."""
import asyncio
from apex.core.backtest import BacktestEngine
from apex.adapters.data.mock_adapter import MockAdapter
from apex.domain.enums import Timeframe


def test_backtest_engine_causality_and_execution():
    mock_adapter = MockAdapter(base_price=2500.0)
    bars = asyncio.run(mock_adapter.get_ohlcv("RELIANCE.NS", Timeframe.M15, 60))
    
    engine = BacktestEngine()
    summary = engine.run(bars, initial_capital=100000.0, warmup_bars=25)
    
    assert summary.symbol == "RELIANCE.NS"
    assert summary.total_bars == 60
    assert summary.initial_capital == 100000.0
    assert len(summary.equity_curve) > 0
    assert summary.max_drawdown_pct >= 0.0
    assert isinstance(summary.trades, list)


def test_backtest_statutory_friction_deduction():
    engine = BacktestEngine()
    turnover = 100000.0  # ₹1 Lakh trade
    friction_buy = engine.calculate_statutory_friction(turnover=turnover, shares=40, is_buy=True)
    friction_sell = engine.calculate_statutory_friction(turnover=turnover, shares=40, is_buy=False)
    
    # Assert friction includes brokerage, STT, turnover, GST, stamp, DP charges, and slippage
    assert friction_buy > 0.0
    assert friction_sell > 0.0
    # In delivery trading, sell-side includes CDSL DP charge (₹18.76) which exceeds buy-side stamp duty (₹15.00)
    assert friction_sell > friction_buy

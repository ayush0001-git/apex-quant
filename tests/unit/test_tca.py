# apex-quant/tests/unit/test_tca.py
"""Unit tests for Transaction Cost Analysis (TCA)."""
from datetime import datetime, timedelta
from apex.core.tca import TCAEngine, TradeExecutionRecord
from apex.domain.enums import Direction, MarketRegime


def test_tca_implementation_shortfall_calculation():
    # Long order: arrival=1000, fill=1001 -> +10 bps
    sf_long = TCAEngine.calculate_implementation_shortfall(1000.0, 1001.0, Direction.LONG)
    assert round(sf_long, 1) == 10.0

    # Short order: arrival=1000, fill=999 -> +10 bps
    sf_short = TCAEngine.calculate_implementation_shortfall(1000.0, 999.0, Direction.SHORT)
    assert round(sf_short, 1) == 10.0


def test_tca_shortfall_decomposition():
    decomp = TCAEngine.decompose_shortfall(
        arrival_price=2000.0,
        fill_price=2001.5,
        direction=Direction.LONG,
        statutory_friction_inr=50.0,
        turnover_inr=100_000.0,
    )
    assert "total_shortfall_bps" in decomp
    assert "spread_cost_bps" in decomp
    assert "impact_cost_bps" in decomp
    assert "statutory_friction_bps" in decomp
    assert decomp["total_shortfall_bps"] > 0.0


def test_tca_report_analysis():
    now = datetime.now()
    records = [
        TradeExecutionRecord(
            trade_id="T1",
            symbol="RELIANCE.NS",
            direction=Direction.LONG,
            timestamp=now - timedelta(hours=1),
            arrival_price=2500.0,
            fill_price=2501.0,
            shares=40,
            turnover_inr=100_040.0,
            regime=MarketRegime.BULL_EXPANSION,
            pre_trade_expected_slippage_bps=5.0,
            realized_slippage_bps=4.0,
            statutory_friction_inr=45.0,
        ),
        TradeExecutionRecord(
            trade_id="T2",
            symbol="TCS.NS",
            direction=Direction.LONG,
            timestamp=now,
            arrival_price=3500.0,
            fill_price=3502.0,
            shares=30,
            turnover_inr=105_060.0,
            regime=MarketRegime.RANGE_COMPRESSION,
            pre_trade_expected_slippage_bps=5.0,
            realized_slippage_bps=5.7,
            statutory_friction_inr=50.0,
        ),
    ]

    report = TCAEngine.analyze_executions(records)
    assert report.total_trades_analyzed == 2
    assert report.total_turnover_inr > 200_000.0
    assert report.mean_implementation_shortfall_bps > 0.0
    assert len(report.regime_breakdown) == 2
    assert "BULL_EXPANSION" in report.regime_breakdown

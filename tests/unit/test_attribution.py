# apex-quant/tests/unit/test_attribution.py
"""Unit tests for PnL Attribution & Walk-Forward Validation."""
from apex.core.attribution import PnLAttributionEngine, DailyPnLAttribution
from apex.domain.enums import MarketRegime
import numpy as np


def test_pnl_attribution_aggregation():
    records = [
        DailyPnLAttribution(
            trade_date="2026-10-20",
            total_pnl_inr=1500.0,
            ta_signal_pnl=600.0,
            factor_alpha_pnl=500.0,
            regime_timing_pnl=250.0,
            options_gex_pnl=150.0,
            llm_throttle_savings=200.0,
            total_friction_drag=80.0,
            active_regime=MarketRegime.BULL_EXPANSION,
        ),
        DailyPnLAttribution(
            trade_date="2026-10-21",
            total_pnl_inr=1200.0,
            ta_signal_pnl=400.0,
            factor_alpha_pnl=450.0,
            regime_timing_pnl=200.0,
            options_gex_pnl=150.0,
            llm_throttle_savings=150.0,
            total_friction_drag=75.0,
            active_regime=MarketRegime.RANGE_COMPRESSION,
        ),
    ]

    report = PnLAttributionEngine.attribute_pnl(records)
    assert report.total_pnl_inr == 2700.0
    assert report.total_friction_inr == 155.0
    assert report.ta_signal_pct > 0.0
    assert report.factor_alpha_pct > 0.0
    assert report.is_alpha_diversified is True


def test_walk_forward_window_simulation():
    np.random.seed(42)
    synthetic_rets = list(np.random.normal(0.001, 0.012, 100))
    windows = PnLAttributionEngine.simulate_walk_forward(synthetic_rets, in_sample_bars=40, out_of_sample_bars=15)

    assert len(windows) > 0
    w1 = windows[0]
    assert w1.window_id == 1
    assert isinstance(w1.in_sample_sharpe, float)
    assert isinstance(w1.out_of_sample_sharpe, float)

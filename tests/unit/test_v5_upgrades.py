# apex-quant/tests/unit/test_v5_upgrades.py
"""Unit tests for ported V5 institutional components: VetoService & PTJExitBlueprint."""
from apex.core.vetoes import VetoService
from apex.core.exit_manager import PTJExitBlueprint
from apex.domain.enums import Direction


def test_wyckoff_volume_veto():
    # Breakout on weak volume (< 1.0x) must fire hard veto
    res = VetoService.evaluate_wyckoff_volume(is_breakout=True, is_pullback=False, volume_ratio=0.85)
    assert res is not None
    assert res.is_vetoed is True
    assert res.veto_name == "wyckoff_upthrust_weak_effort"
    assert res.severity == "hard"

    # Breakout on moderate volume (1.05x < 1.10x) must fire soft veto
    res2 = VetoService.evaluate_wyckoff_volume(is_breakout=True, is_pullback=False, volume_ratio=1.05)
    assert res2 is not None
    assert res2.is_vetoed is True
    assert res2.veto_name == "wyckoff_weak_volume"
    assert res2.severity == "soft"

    # Healthy breakout with volume > 1.10x must pass
    res3 = VetoService.evaluate_wyckoff_volume(is_breakout=True, is_pullback=False, volume_ratio=1.35)
    assert res3 is None

    # Healthy pullback dry-up with volume < 1.0x must pass
    res4 = VetoService.evaluate_wyckoff_volume(is_breakout=False, is_pullback=True, volume_ratio=0.75)
    assert res4 is None


def test_multi_timeframe_weekly_trend_lock():
    # Long setup when weekly close < weekly EMA20 must be hard-vetoed
    res = VetoService.evaluate_weekly_trend_lock(
        daily_direction=Direction.LONG,
        weekly_close=100.0,
        weekly_ema20=105.0,
    )
    assert res is not None
    assert res.is_vetoed is True
    assert res.veto_name == "weekly_trend_opposed"
    assert res.severity == "hard"

    # Long setup when weekly close >= weekly EMA20 must pass
    res2 = VetoService.evaluate_weekly_trend_lock(
        daily_direction=Direction.LONG,
        weekly_close=110.0,
        weekly_ema20=105.0,
    )
    assert res2 is None


def test_commodity_opposed_veto():
    # ONGC with crude in severe downtrend (< -5.0%) must be vetoed
    res = VetoService.evaluate_commodity_opposed("ONGC.NS", Direction.LONG, commodity_return_20d_pct=-8.2)
    assert res is not None
    assert res.is_vetoed is True
    assert res.veto_name == "commodity_opposed"

    # Non-cyclical stock should not be affected
    res2 = VetoService.evaluate_commodity_opposed("HCLTECH.NS", Direction.LONG, commodity_return_20d_pct=-10.0)
    assert res2 is None


def test_ptj_exit_blueprint_milestones():
    # Entry at 100, Stop at 96 (Risk R = 4, ATR = 2.0)
    # Milestone 1: +1.0R = 104
    # Milestone 2: +1.5R = 106 (Takes 50% profit, moves SL to breakeven ~100.20)
    # Target: +2.5R = 110
    mgr = PTJExitBlueprint(entry=100.0, stop=96.0, atr=2.0, rr_target=2.5)
    assert mgr.risk_r == 4.0
    assert mgr.target == 110.0

    # Bar 1: Normal progress to 102
    step1 = mgr.update(current_high=102.0, current_low=99.5, current_close=101.5)
    assert step1.action == "HOLD"
    assert step1.is_closed is False

    # Bar 2: Hits Milestone 2 (+1.5R at 106.5)
    step2 = mgr.update(current_high=106.5, current_low=103.0, current_close=106.0)
    assert step2.action == "PARTIAL_EXIT_50PCT"
    assert step2.exit_pct == 50.0
    assert step2.current_stop >= 100.0  # Breakeven locked
    assert mgr.position_remaining_pct == 50.0

    # Bar 3: Hits full target at 110.5
    step3 = mgr.update(current_high=110.5, current_low=107.0, current_close=110.0)
    assert step3.action == "TARGET_FULL_EXIT"
    assert step3.is_closed is True


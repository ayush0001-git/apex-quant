# apex-quant/tests/unit/test_decision.py
"""Unit tests for DecisionEngine aggregation and fail-closed defaults."""
from datetime import datetime
from apex.core.decision import DecisionEngine
from apex.domain.enums import Direction, MarketRegime
from apex.domain.models import FeatureSnapshot, Forecast, DebateResult


def test_decision_engine_fail_closed_when_debate_is_none():
    features = FeatureSnapshot(
        symbol="INFY.NS",
        timestamp=datetime(2026, 10, 23, 15, 0),
        spot_price=1500.0,
        indicators={"atr_14": 20.0},
        patterns=(),
        confluence_score=80.0,
        volume_ratio=1.8,
        regime=MarketRegime.BULL_EXPANSION,
    )
    intent = DecisionEngine.evaluate(features=features, forecast=None, debate=None)
    assert intent.direction == Direction.HOLD
    assert intent.conviction == 0
    assert intent.entry == features.spot_price


def test_decision_engine_produces_trade_intent():
    features = FeatureSnapshot(
        symbol="INFY.NS",
        timestamp=datetime(2026, 10, 23, 15, 0),
        spot_price=1500.0,
        indicators={"atr_14": 20.0},
        patterns=("BULLISH_ENGULFING",),
        confluence_score=85.0,
        volume_ratio=1.8,
        regime=MarketRegime.BULL_EXPANSION,
    )
    debate = DebateResult(
        action=Direction.LONG,
        conviction=88,
        entry_zone=(1498.0, 1502.0),
        stop_loss=1470.0,
        targets=(1540.0, 1570.0),
        reasoning_hash="hash123",
    )
    intent = DecisionEngine.evaluate(features=features, forecast=None, debate=debate)
    assert intent.direction == Direction.LONG
    assert intent.conviction == 88
    assert intent.entry == 1500.0
    assert intent.stop == 1470.0
    assert intent.targets == (1540.0, 1570.0)

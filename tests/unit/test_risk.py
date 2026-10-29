# apex-quant/tests/unit/test_risk.py
"""Unit tests for RiskGate deterministic mathematical validations."""
from datetime import datetime
import pytest
from apex.core.risk import RiskGate
from apex.domain.config import Settings
from apex.domain.enums import Direction, GateStatus, KillReason, MarketRegime
from apex.domain.models import FeatureSnapshot, DebateResult, TradeIntent


def make_dummy_intent(entry: float = 1000.0, stop: float = 980.0, target: float = 1060.0, direction: Direction = Direction.LONG) -> TradeIntent:
    features = FeatureSnapshot(
        symbol="RELIANCE.NS",
        timestamp=datetime(2026, 10, 23, 15, 0),
        spot_price=entry,
        indicators={"atr_14": 15.0},
        patterns=(),
        confluence_score=80.0,
        volume_ratio=1.5,
        regime=MarketRegime.BULL_EXPANSION,
    )
    debate = DebateResult(
        action=direction,
        conviction=85,
        entry_zone=(entry - 2, entry + 2),
        stop_loss=stop,
        targets=(target,),
        reasoning_hash="h123",
    )
    return TradeIntent(
        symbol="RELIANCE.NS",
        direction=direction,
        entry=entry,
        stop=stop,
        targets=(target,),
        conviction=85,
        feature_snapshot=features,
        forecast=None,
        debate=debate,
    )


def test_risk_gate_approves_healthy_trade():
    settings = Settings.load()
    gate = RiskGate(settings)
    intent = make_dummy_intent(entry=1000.0, stop=980.0, target=1070.0)
    decision = gate.evaluate(intent, portfolio_equity=100000.0)

    assert decision.status == GateStatus.APPROVED
    assert decision.kill_reason == KillReason.NONE
    assert decision.position_size is not None
    assert decision.position_size > 0
    assert decision.estimated_statutory_friction > 0


def test_risk_gate_drawdown_circuit_breaker():
    settings = Settings.load()
    gate = RiskGate(settings)
    intent = make_dummy_intent()
    # Daily loss of 2,500 on 100,000 equity is 2.5% loss >= 2.0% cap
    decision = gate.evaluate(intent, portfolio_equity=100000.0, daily_pnl=-2500.0)

    assert decision.status == GateStatus.REJECTED
    assert decision.kill_reason == KillReason.MAX_DAILY_DRAWDOWN


def test_risk_gate_friction_rule_rejection():
    settings = Settings.load()
    gate = RiskGate(settings)
    # Tiny target where profit is swallowed by statutory friction
    intent = make_dummy_intent(entry=1000.0, stop=995.0, target=1000.50)
    decision = gate.evaluate(intent, portfolio_equity=100000.0)

    assert decision.status == GateStatus.REJECTED
    assert decision.kill_reason == KillReason.NEGATIVE_NET_RR


def test_risk_gate_consecutive_loss_throttle():
    settings = Settings.load()
    gate = RiskGate(settings)
    intent = make_dummy_intent(entry=1000.0, stop=980.0, target=1070.0)

    normal_decision = gate.evaluate(intent, portfolio_equity=100000.0, consecutive_losses=0)
    throttled_decision = gate.evaluate(intent, portfolio_equity=100000.0, consecutive_losses=3)

    assert normal_decision.status == GateStatus.APPROVED
    assert throttled_decision.status == GateStatus.APPROVED
    assert throttled_decision.position_size == normal_decision.position_size // 2

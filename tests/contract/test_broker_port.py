# apex-quant/tests/contract/test_broker_port.py
"""Contract tests asserting BrokerPort interface compliance."""
import asyncio
from datetime import datetime
from apex.adapters.broker.paper_broker import PaperBroker
from apex.adapters.broker.null_broker import NullBroker
from apex.domain.enums import Direction, GateStatus, KillReason, MarketRegime
from apex.domain.models import FeatureSnapshot, DebateResult, TradeIntent, RiskDecision
from apex.ports.broker_port import BrokerPort


def make_approved_payload():
    features = FeatureSnapshot(
        symbol="SBIN.NS",
        timestamp=datetime(2026, 10, 23, 15, 0),
        spot_price=800.0,
        indicators={},
        patterns=(),
        confluence_score=80.0,
        volume_ratio=1.5,
        regime=MarketRegime.BULL_EXPANSION,
    )
    debate = DebateResult(
        action=Direction.LONG,
        conviction=85,
        entry_zone=(798.0, 802.0),
        stop_loss=790.0,
        targets=(820.0,),
        reasoning_hash="h1",
    )
    intent = TradeIntent(
        symbol="SBIN.NS",
        direction=Direction.LONG,
        entry=800.0,
        stop=790.0,
        targets=(820.0,),
        conviction=85,
        feature_snapshot=features,
        forecast=None,
        debate=debate,
    )
    risk = RiskDecision(
        status=GateStatus.APPROVED,
        reason="Clean",
        kill_reason=KillReason.NONE,
        position_size=100.0,
        max_capital_risk_pct=1.0,
        net_rr_ratio=2.5,
        estimated_statutory_friction=50.0,
    )
    return intent, risk


def test_paper_broker_implements_broker_port():
    broker: BrokerPort = PaperBroker()
    intent, risk = make_approved_payload()

    res = asyncio.run(broker.submit_intent(intent, risk))
    assert res["status"] == "FILLED"
    assert res["symbol"] == "SBIN.NS"
    assert res["quantity"] == 100.0


def test_null_broker_implements_broker_port():
    broker: BrokerPort = NullBroker()
    intent, risk = make_approved_payload()

    res = asyncio.run(broker.submit_intent(intent, risk))
    assert res["status"] == "ADVISORY_ONLY"

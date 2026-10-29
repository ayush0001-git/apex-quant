# apex-quant/tests/unit/test_execution.py
"""Unit tests for ExecutionService."""
import asyncio
from datetime import datetime
from apex.adapters.broker.paper_broker import PaperBroker
from apex.adapters.storage.sqlite_audit import SQLiteAuditAdapter
from apex.core.execution import ExecutionService
from apex.domain.enums import Direction, GateStatus, KillReason, MarketRegime
from apex.domain.models import FeatureSnapshot, DebateResult, TradeIntent, RiskDecision


def test_execution_service_runs_approved_order(tmp_path):
    db_file = tmp_path / "test_audit.db"
    broker = PaperBroker()
    storage = SQLiteAuditAdapter(db_file)
    svc = ExecutionService(broker=broker, storage=storage, algo_id="TEST_ALGO")

    features = FeatureSnapshot(
        symbol="WIPRO.NS",
        timestamp=datetime(2026, 10, 23, 15, 0),
        spot_price=550.0,
        indicators={},
        patterns=(),
        confluence_score=80.0,
        volume_ratio=1.5,
        regime=MarketRegime.BULL_EXPANSION,
    )
    debate = DebateResult(
        action=Direction.LONG,
        conviction=85,
        entry_zone=(548.0, 552.0),
        stop_loss=540.0,
        targets=(570.0,),
        reasoning_hash="h1",
    )
    intent = TradeIntent(
        symbol="WIPRO.NS",
        direction=Direction.LONG,
        entry=550.0,
        stop=540.0,
        targets=(570.0,),
        conviction=85,
        feature_snapshot=features,
        forecast=None,
        debate=debate,
    )
    risk = RiskDecision(
        status=GateStatus.APPROVED,
        reason="Approved",
        kill_reason=KillReason.NONE,
        position_size=50.0,
        max_capital_risk_pct=1.0,
        net_rr_ratio=2.5,
        estimated_statutory_friction=40.0,
    )

    result = asyncio.run(svc.execute(intent, risk))
    assert result["status"] == "FILLED"
    assert "audit_id" in result
    assert result["audit_id"].startswith("AUDIT_")

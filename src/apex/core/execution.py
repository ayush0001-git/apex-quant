# apex-quant/src/apex/core/execution.py
"""ExecutionService: The ONLY module permitted to hold a BrokerPort reference.

Strict single-ownership rules:
1. Never makes trading decisions.
2. Only accepts TradeIntent paired with an APPROVED RiskDecision.
3. Submits order to BrokerPort and logs immutable AuditRecord to StoragePort.
"""
import uuid
from datetime import datetime, timezone
from typing import Mapping, Any
from ..domain.models import TradeIntent, RiskDecision, AuditRecord
from ..domain.enums import GateStatus
from ..ports.broker_port import BrokerPort
from ..ports.storage_port import StoragePort


class ExecutionService:
    """Dispatches approved orders and ensures SEBI-compliant audit trail recording."""

    def __init__(
        self,
        broker: BrokerPort,
        storage: StoragePort,
        algo_id: str = "APEX_ALGO_V1",
    ) -> None:
        self.broker = broker
        self.storage = storage
        self.algo_id = algo_id

    async def execute(
        self, intent: TradeIntent, risk: RiskDecision
    ) -> Mapping[str, Any]:
        # Refuse execution if risk gate rejected the trade
        if risk.status != GateStatus.APPROVED:
            # Still record audit of rejection
            audit_id = f"AUDIT_REJ_{uuid.uuid4().hex[:12].upper()}"
            record = AuditRecord(
                audit_id=audit_id,
                timestamp_utc=datetime.now(timezone.utc),
                algo_id=self.algo_id,
                symbol=intent.symbol,
                intent=intent,
                risk=risk,
            )
            await self.storage.save_audit(record)
            return {
                "order_id": None,
                "status": "REJECTED_BY_RISK_GATE",
                "reason": risk.reason,
                "audit_id": audit_id,
            }

        # Write-Ahead Audit Record (F21: persist intent before broker dispatch)
        audit_id = f"AUDIT_{uuid.uuid4().hex[:12].upper()}"
        record = AuditRecord(
            audit_id=audit_id,
            timestamp_utc=datetime.now(timezone.utc),
            algo_id=self.algo_id,
            symbol=intent.symbol,
            intent=intent,
            risk=risk,
        )
        await self.storage.save_audit(record)

        # Submit to broker with write-ahead protection
        try:
            order_result = await self.broker.submit_intent(intent, risk)
        except Exception as exc:
            return {
                "order_id": None,
                "status": "BROKER_SUBMISSION_FAILED",
                "error": str(exc),
                "audit_id": audit_id,
            }

        return {
            **order_result,
            "audit_id": audit_id,
        }

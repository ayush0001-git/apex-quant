# apex-quant/src/apex/adapters/broker/paper_broker.py
"""PaperBroker: Simulates order fills with realistic slippage. Zero live capital."""
import uuid
from datetime import datetime, timezone
from typing import Mapping, Any
from ...domain.models import TradeIntent, RiskDecision
from ...domain.enums import Direction, GateStatus
from ...ports.broker_port import BrokerPort


class PaperBroker(BrokerPort):
    """Simulated execution engine for paper trading."""

    def __init__(self, slippage_pct: float = 0.0005) -> None:
        self.slippage_pct = slippage_pct
        self.positions: dict[str, dict[str, Any]] = {}
        self.orders: list[dict[str, Any]] = []

    async def submit_intent(
        self, intent: TradeIntent, risk: RiskDecision
    ) -> Mapping[str, Any]:
        if risk.status != GateStatus.APPROVED:
            return {
                "order_id": None,
                "status": "REJECTED_BY_RISK",
                "reason": risk.reason,
            }

        order_id = f"PAPER_{uuid.uuid4().hex[:8].upper()}"
        direction = intent.direction

        # Apply realistic slippage on entry
        if direction == Direction.LONG:
            fill_price = round(intent.entry * (1.0 + self.slippage_pct), 2)
        elif direction == Direction.SHORT:
            fill_price = round(intent.entry * (1.0 - self.slippage_pct), 2)
        else:
            fill_price = intent.entry

        order_record = {
            "order_id": order_id,
            "symbol": intent.symbol,
            "direction": direction.value,
            "quantity": risk.position_size,
            "entry_target": intent.entry,
            "fill_price": fill_price,
            "stop_loss": intent.stop,
            "targets": list(intent.targets),
            "status": "FILLED",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        self.orders.append(order_record)
        self.positions[intent.symbol] = order_record

        return order_record

    async def get_positions(self) -> Mapping[str, Any]:
        return dict(self.positions)

    async def emergency_cancel_all(self) -> bool:
        self.positions.clear()
        return True

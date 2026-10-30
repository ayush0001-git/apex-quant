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

        # Position tracking and aggregation (F21)
        sym = intent.symbol
        new_qty = float(risk.position_size or 0.0)
        if sym in self.positions and self.positions[sym].get("direction") == direction.value:
            existing = self.positions[sym]
            old_qty = float(existing.get("quantity", 0.0))
            tot_qty = old_qty + new_qty
            avg_price = round(((existing.get("fill_price", fill_price) * old_qty) + (fill_price * new_qty)) / (tot_qty + 1e-8), 2)
            self.positions[sym] = {
                **existing,
                "quantity": tot_qty,
                "fill_price": avg_price,
                "last_order_id": order_id,
                "timestamp": order_record["timestamp"],
            }
        else:
            self.positions[sym] = dict(order_record)

        return order_record

    async def get_positions(self) -> Mapping[str, Any]:
        return dict(self.positions)

    async def emergency_cancel_all(self) -> bool:
        self.positions.clear()
        return True

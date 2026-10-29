# apex-quant/src/apex/adapters/broker/null_broker.py
"""NullBroker: Scan-only advisory mode. Emits zero orders."""
from typing import Mapping, Any
from ...domain.models import TradeIntent, RiskDecision
from ...ports.broker_port import BrokerPort


class NullBroker(BrokerPort):
    """Scan-only no-op broker."""

    async def submit_intent(
        self, intent: TradeIntent, risk: RiskDecision
    ) -> Mapping[str, Any]:
        return {
            "order_id": "NULL_ADVISORY",
            "status": "ADVISORY_ONLY",
            "symbol": intent.symbol,
            "direction": intent.direction.value,
            "entry": intent.entry,
            "stop": intent.stop,
            "targets": list(intent.targets),
        }

    async def get_positions(self) -> Mapping[str, Any]:
        return {}

    async def emergency_cancel_all(self) -> bool:
        return True

# apex-quant/src/apex/ports/broker_port.py
"""Abstract interface for Broker Execution."""
from abc import ABC, abstractmethod
from typing import Mapping, Any
from ..domain.models import TradeIntent, RiskDecision


class BrokerPort(ABC):
    """Port for order submission. Only ExecutionService holds this reference."""

    @abstractmethod
    async def submit_intent(
        self, intent: TradeIntent, risk: RiskDecision
    ) -> Mapping[str, Any]:
        """Submit an approved intent with Algo ID tagging and static IP route."""
        pass

    @abstractmethod
    async def get_positions(self) -> Mapping[str, Any]:
        """Fetch current open positions and margin utilization."""
        pass

    @abstractmethod
    async def emergency_cancel_all(self) -> bool:
        """Trigger exchange-wide kill switch."""
        pass

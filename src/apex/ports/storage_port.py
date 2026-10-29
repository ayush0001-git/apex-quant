# apex-quant/src/apex/ports/storage_port.py
"""Abstract interface for Storage & Audit Trails."""
from abc import ABC, abstractmethod
from typing import Sequence, List, Mapping, Any
from ..domain.models import AuditRecord, Bar
from ..domain.enums import Timeframe


class StoragePort(ABC):
    """Port for immutable audit logging and historical persistence."""

    @abstractmethod
    async def save_audit(self, record: AuditRecord) -> None:
        """Persist SEBI compliance audit trail."""
        pass

    @abstractmethod
    async def load_history(
        self, symbol: str, timeframe: Timeframe, lookback: int
    ) -> Sequence[Bar]:
        """Load local parquet bars for zero-network testing."""
        pass

    async def get_recent_logs(self, limit: int = 50) -> List[Mapping[str, Any]]:
        """Retrieve recent audit entries for compliance and terminal display."""
        return []

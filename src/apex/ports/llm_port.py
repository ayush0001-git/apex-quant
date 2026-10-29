# apex-quant/src/apex/ports/llm_port.py
"""Abstract interface for Two-Tier LLM Intelligence."""
from abc import ABC, abstractmethod
from typing import Sequence
from ..domain.models import FeatureSnapshot, Forecast, DebateResult


class LLMPort(ABC):
    """Two-tier interface: Free pool for scanning, paid gate for synthesis."""

    @abstractmethod
    async def scan_batch(self, symbols: Sequence[str]) -> Sequence[str]:
        """Fast pre-market / background candidate screener (implements freellmapi)."""
        pass

    @abstractmethod
    async def synthesize(
        self,
        symbol: str,
        features: FeatureSnapshot,
        forecast: Forecast | None,
    ) -> DebateResult | None:
        """Adversarial Bull/Bear debate (implements PaidGate / direct model).
        Returns None on timeout/failure -> DecisionEngine defaults to HOLD.
        """
        pass

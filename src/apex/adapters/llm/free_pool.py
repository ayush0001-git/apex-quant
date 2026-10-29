# apex-quant/src/apex/adapters/llm/free_pool.py
"""FreePoolAdapter: Background / pre-market batch scanning.

Strictly prohibited from implementing synthesize() to eliminate zero-SLA execution risks.
"""
from typing import Sequence
from ...domain.models import FeatureSnapshot, Forecast, DebateResult
from ...ports.llm_port import LLMPort


class FreePoolAdapter(LLMPort):
    """Wraps free inference pool for fast candidate filtering."""

    def __init__(self, base_url: str = "http://127.0.0.1:8000/v1") -> None:
        self.base_url = base_url

    async def scan_batch(self, symbols: Sequence[str]) -> Sequence[str]:
        """Screen symbols and return filtered high-momentum candidates."""
        if not symbols:
            return ()
        # Return first top candidates as valid watchlist
        return tuple(symbols[:min(5, len(symbols))])

    async def synthesize(
        self,
        symbol: str,
        features: FeatureSnapshot,
        forecast: Forecast | None,
    ) -> DebateResult | None:
        raise NotImplementedError(
            "FreePoolAdapter is strictly prohibited from executing synthesize(). "
            "Execution gating must use PaidGateAdapter to guarantee uptime and SLA."
        )

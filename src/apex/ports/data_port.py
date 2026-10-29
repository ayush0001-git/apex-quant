# apex-quant/src/apex/ports/data_port.py
"""Abstract interface for Market Data."""
from abc import ABC, abstractmethod
from typing import AsyncIterator, Sequence
from ..domain.models import Bar
from ..domain.enums import Timeframe


class MarketDataPort(ABC):
    """Port for normalized market data ingestion."""

    @abstractmethod
    async def get_ohlcv(
        self, symbol: str, timeframe: Timeframe, lookback: int
    ) -> Sequence[Bar]:
        """Fetch historical bars ending strictly at the last closed candle."""
        pass

    @abstractmethod
    async def stream_bars(
        self, symbols: Sequence[str], timeframe: Timeframe
    ) -> AsyncIterator[Bar]:
        """Stream real-time bars with is_closed=True flag."""
        pass

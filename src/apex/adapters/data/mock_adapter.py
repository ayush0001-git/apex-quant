# apex-quant/src/apex/adapters/data/mock_adapter.py
"""Mock data adapter producing deterministic, synthetic Bars for offline testing."""
from datetime import datetime, timedelta
from typing import AsyncIterator, Sequence
from ...domain.models import Bar
from ...domain.enums import Timeframe
from ...ports.data_port import MarketDataPort


class MockAdapter(MarketDataPort):
    """Produces deterministic test bars without network I/O."""

    def __init__(self, base_price: float = 2500.0) -> None:
        self.base_price = base_price

    async def get_ohlcv(
        self, symbol: str, timeframe: Timeframe, lookback: int
    ) -> Sequence[Bar]:
        bars: list[Bar] = []
        now = datetime(2026, 10, 23, 15, 30, 0)
        price = self.base_price

        for i in range(lookback):
            ts = now - timedelta(minutes=15 * (lookback - i))
            # Predictable oscillating pattern with valid volume
            delta = (i % 5) - 2.0
            o = price
            c = price + delta
            h = max(o, c) + 1.5
            l = min(o, c) - 1.5
            v = 100000.0 + (i * 500.0)
            price = c

            bars.append(
                Bar(
                    symbol=symbol,
                    timeframe=timeframe,
                    timestamp=ts,
                    open=round(o, 2),
                    high=round(h, 2),
                    low=round(l, 2),
                    close=round(c, 2),
                    volume=round(v, 2),
                    is_closed=True,
                )
            )
        return bars

    async def stream_bars(
        self, symbols: Sequence[str], timeframe: Timeframe
    ) -> AsyncIterator[Bar]:
        bars = await self.get_ohlcv(symbols[0], timeframe, 1)
        for b in bars:
            yield b

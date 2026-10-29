# apex-quant/src/apex/adapters/data/yfinance_feed.py
"""Zero-cost MarketDataPort adapter using yfinance for NSE (.NS) and BSE (.BO) symbols."""
import asyncio
import math
from datetime import datetime
from typing import AsyncIterator, Sequence
import yfinance as yf
from ...domain.models import Bar
from ...domain.enums import Timeframe
from ...ports.data_port import MarketDataPort


TF_MAP = {
    Timeframe.M1: "1m",
    Timeframe.M5: "5m",
    Timeframe.M15: "15m",
    Timeframe.H1: "60m",
    Timeframe.D1: "1d",
}


class YFinanceFeed(MarketDataPort):
    """Fetches real-time/historical candles for Indian stocks without API keys."""

    def __init__(self, timeout_s: int = 15) -> None:
        self.timeout_s = timeout_s

    async def get_ohlcv(
        self, symbol: str, timeframe: Timeframe, lookback: int
    ) -> Sequence[Bar]:
        interval = TF_MAP[timeframe]
        
        # Run blocking network call in threadpool
        loop = asyncio.get_running_loop()
        df = await loop.run_in_executor(
            None,
            lambda: yf.download(
                tickers=symbol,
                period="1mo" if timeframe != Timeframe.D1 else "1y",
                interval=interval,
                progress=False,
                auto_adjust=True,
            )
        )

        if df is None or df.empty:
            return ()

        # Drop any row containing NaN prices
        df = df.dropna()
        records = df.tail(lookback + 1)
        bars: list[Bar] = []

        for ts, row in records.iterrows():
            # In multi-index columns, extract scalar
            o = float(row["Open"].iloc[0] if hasattr(row["Open"], "iloc") else row["Open"])
            h = float(row["High"].iloc[0] if hasattr(row["High"], "iloc") else row["High"])
            l = float(row["Low"].iloc[0] if hasattr(row["Low"], "iloc") else row["Low"])
            c = float(row["Close"].iloc[0] if hasattr(row["Close"], "iloc") else row["Close"])
            v = float(row["Volume"].iloc[0] if hasattr(row["Volume"], "iloc") else row["Volume"])

            # Filter out NaNs, zeroes, or negative prices
            if math.isnan(o) or math.isnan(h) or math.isnan(l) or math.isnan(c) or math.isnan(v):
                continue
            if v <= 0 or l <= 0:
                continue

            # Convert pandas Timestamp to standard datetime
            dt = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts

            bars.append(
                Bar(
                    symbol=symbol,
                    timeframe=timeframe,
                    timestamp=dt,
                    open=round(o, 2),
                    high=round(h, 2),
                    low=round(l, 2),
                    close=round(c, 2),
                    volume=round(v, 2),
                    is_closed=True,
                )
            )

        # Return strictly the requested lookback of closed candles
        return tuple(bars[-lookback:])

    async def stream_bars(
        self, symbols: Sequence[str], timeframe: Timeframe
    ) -> AsyncIterator[Bar]:
        bars = await self.get_ohlcv(symbols[0], timeframe, 1)
        for b in bars:
            yield b

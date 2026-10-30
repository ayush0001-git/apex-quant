# apex-quant/src/apex/adapters/data/yfinance_feed.py
"""Zero-cost MarketDataPort adapter using yfinance for NSE (.NS) and BSE (.BO) symbols."""
import asyncio
import math
from datetime import datetime, timezone, timedelta
from typing import AsyncIterator, Sequence, Optional
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

IST_OFFSET = timedelta(hours=5, minutes=30)

TF_DELTA_MAP = {
    Timeframe.M1: timedelta(minutes=1),
    Timeframe.M5: timedelta(minutes=5),
    Timeframe.M15: timedelta(minutes=15),
    Timeframe.H1: timedelta(hours=1),
    Timeframe.D1: timedelta(days=1),
}


def is_bar_closed(
    timestamp: datetime,
    timeframe: Timeframe,
    now: Optional[datetime] = None,
) -> bool:
    """Determine whether an OHLCV candle has finalized or is currently forming.
    
    Prevents lookahead / causality leaks on active intraday or live daily candles.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    # Normalize timestamp to UTC
    if timestamp.tzinfo is None:
        # If naive, assume IST (Indian Market) and convert to UTC
        bar_dt = timestamp.replace(tzinfo=timezone(IST_OFFSET)).astimezone(timezone.utc)
    else:
        bar_dt = timestamp.astimezone(timezone.utc)

    if timeframe == Timeframe.D1:
        # Indian market closes at 15:30 IST (10:00 UTC)
        now_ist = now.astimezone(timezone(IST_OFFSET))
        bar_ist = bar_dt.astimezone(timezone(IST_OFFSET))
        if bar_ist.date() < now_ist.date():
            return True
        elif bar_ist.date() == now_ist.date():
            # If today, closed only if current time >= 15:30 IST
            return (now_ist.hour > 15) or (now_ist.hour == 15 and now_ist.minute >= 30)
        else:
            return False
    else:
        delta = TF_DELTA_MAP.get(timeframe, timedelta(minutes=15))
        return (bar_dt + delta) <= now


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
                    is_closed=is_bar_closed(dt, timeframe),
                )
            )

        result_bars = tuple(bars[-lookback:])

        # Log fetch metadata for point-in-time reproducibility
        if result_bars:
            try:
                from ...core.data_integrity import compute_bars_checksum, log_fetch_metadata
                checksum = compute_bars_checksum(result_bars)
                log_fetch_metadata(
                    source="yfinance",
                    symbol=symbol,
                    row_count=len(result_bars),
                    checksum=checksum,
                    timeframe=timeframe.value if hasattr(timeframe, "value") else str(timeframe),
                )
            except Exception:
                pass

        return result_bars

    async def stream_bars(
        self, symbols: Sequence[str], timeframe: Timeframe
    ) -> AsyncIterator[Bar]:
        bars = await self.get_ohlcv(symbols[0], timeframe, 1)
        for b in bars:
            yield b

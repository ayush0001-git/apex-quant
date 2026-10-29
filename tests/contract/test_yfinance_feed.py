# apex-quant/tests/contract/test_yfinance_feed.py
"""Contract test verifying YFinanceFeed satisfies MarketDataPort interface."""
import asyncio
from apex.adapters.data.yfinance_feed import YFinanceFeed
from apex.domain.enums import Timeframe
from apex.domain.models import Bar
from apex.ports.data_port import MarketDataPort


def test_yfinance_feed_conforms_to_market_data_port():
    feed: MarketDataPort = YFinanceFeed()
    bars = asyncio.run(feed.get_ohlcv("TCS.NS", Timeframe.D1, 10))

    assert isinstance(bars, (list, tuple))
    assert len(bars) > 0
    for b in bars:
        assert isinstance(b, Bar)
        assert b.symbol == "TCS.NS"
        assert b.timeframe == Timeframe.D1
        assert b.is_closed is True
        assert b.volume > 0
        assert b.high >= b.low

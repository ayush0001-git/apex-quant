# apex-quant/tests/contract/test_data_port.py
"""Contract tests asserting any MarketDataPort implementation honors interface rules."""
import asyncio
from apex.adapters.data.mock_adapter import MockAdapter
from apex.domain.enums import Timeframe
from apex.domain.models import Bar
from apex.ports.data_port import MarketDataPort


def test_mock_adapter_conforms_to_market_data_port():
    adapter: MarketDataPort = MockAdapter(base_price=2450.0)
    bars = asyncio.run(adapter.get_ohlcv("RELIANCE.NS", Timeframe.M15, 20))

    assert isinstance(bars, (list, tuple))
    assert len(bars) == 20
    for b in bars:
        assert isinstance(b, Bar)
        assert b.symbol == "RELIANCE.NS"
        assert b.timeframe == Timeframe.M15
        assert b.is_closed is True
        assert b.volume > 0
        assert b.high >= b.low

# apex-quant/tests/unit/test_bhavcopy.py
"""Unit tests for BhavcopyAdapter historical data parsing and survivorship mitigation."""
import asyncio
import pytest
from apex.adapters.data.bhavcopy_adapter import BhavcopyAdapter
from apex.domain.enums import Timeframe


SAMPLE_BHAVCOPY_CSV = """SYMBOL, SERIES, OPEN, HIGH, LOW, CLOSE, LAST, PREVCLOSE, TOTTRDQTY, TOTTRDVAL, TIMESTAMP, TOTALTRADES, ISIN
RELIANCE, EQ, 2500.0, 2540.0, 2490.0, 2530.0, 2532.0, 2495.0, 5000000, 12600000000, 23-OCT-2026, 120000, INE002A01018
DELISTEDCO, EQ, 120.0, 125.0, 118.0, 121.0, 121.0, 119.0, 200000, 24200000, 23-OCT-2026, 4000, INE999A01099
BONDS1, GB, 100.0, 100.5, 99.5, 100.0, 100.0, 100.0, 5000, 500000, 23-OCT-2026, 50, IN0000000000
"""


def test_bhavcopy_adapter_ingestion_and_series_filter():
    adapter = BhavcopyAdapter()
    loaded = adapter.load_bhavcopy_csv(SAMPLE_BHAVCOPY_CSV)
    
    # Only EQ series should be loaded (2 equities: RELIANCE and DELISTEDCO; BONDS1 GB filtered out)
    assert loaded == 2
    symbols = adapter.get_all_traded_symbols()
    assert "RELIANCE.NS" in symbols
    assert "DELISTEDCO.NS" in symbols
    assert "BONDS1.NS" not in symbols


def test_bhavcopy_adapter_get_ohlcv():
    adapter = BhavcopyAdapter()
    adapter.load_bhavcopy_csv(SAMPLE_BHAVCOPY_CSV)
    
    bars = asyncio.run(adapter.get_ohlcv("DELISTEDCO.NS", Timeframe.D1, 10))
    assert len(bars) == 1
    assert bars[0].symbol == "DELISTEDCO.NS"
    assert bars[0].close == 121.0
    assert bars[0].is_closed is True


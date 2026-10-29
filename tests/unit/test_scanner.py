# apex-quant/tests/unit/test_scanner.py
"""Unit tests for the multi-asset market scanner."""
import asyncio
from apex.core.scanner import ScannerService
from apex.adapters.data.mock_adapter import MockAdapter
from apex.domain.enums import Timeframe, Direction


def test_scanner_single_symbol():
    mock_adapter = MockAdapter()
    scanner = ScannerService(data_port=mock_adapter)
    
    opp = asyncio.run(scanner.scan_symbol("RELIANCE.NS", timeframe=Timeframe.M15, bars_count=40))
    assert opp is not None
    assert opp.symbol == "RELIANCE.NS"
    assert opp.spot_price > 0
    assert opp.opportunity_score >= 0
    assert opp.bias in {Direction.LONG, Direction.SHORT, Direction.HOLD}


def test_scanner_universe():
    mock_adapter = MockAdapter()
    scanner = ScannerService(data_port=mock_adapter)
    
    test_symbols = ["RELIANCE.NS", "TCS.NS", "INFY.NS"]
    results = asyncio.run(scanner.scan_universe(symbols=test_symbols, timeframe=Timeframe.M15, min_opportunity_score=10.0))
    assert len(results) > 0
    for r in results:
        assert r.symbol in test_symbols
        assert r.opportunity_score >= 10.0

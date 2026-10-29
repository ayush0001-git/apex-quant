# apex-quant/tests/unit/test_microstructure.py
"""Unit tests for MicrostructureService (OFI, Kyle's Lambda, VPIN, Microprice)."""
import asyncio
import pytest
from apex.adapters.data.mock_adapter import MockAdapter
from apex.core.microstructure import MicrostructureService
from apex.domain.enums import Timeframe


def test_microstructure_analysis_outputs_complete_snapshot():
    adapter = MockAdapter(base_price=3000.0)
    bars = asyncio.run(adapter.get_ohlcv("TCS.NS", Timeframe.M15, 35))
    
    snapshot = MicrostructureService.analyze_microstructure(bars)
    
    assert snapshot.symbol == "TCS.NS"
    assert isinstance(snapshot.ofi_value, float)
    assert snapshot.kyle_lambda > 0.0
    assert 0.0 <= snapshot.vpin_toxicity <= 1.0
    assert snapshot.microprice > 0.0
    assert snapshot.spread_bps > 0.0


def test_microstructure_vpin_calculation():
    adapter = MockAdapter()
    bars = asyncio.run(adapter.get_ohlcv("RELIANCE.NS", Timeframe.M15, 30))
    
    vpin = MicrostructureService.calculate_vpin(bars, num_buckets=5)
    assert 0.0 <= vpin <= 1.0


def test_microstructure_kyle_lambda_estimation():
    adapter = MockAdapter()
    bars = asyncio.run(adapter.get_ohlcv("RELIANCE.NS", Timeframe.M15, 30))
    
    kyle = MicrostructureService.estimate_kyle_lambda(bars)
    assert kyle >= 0.01


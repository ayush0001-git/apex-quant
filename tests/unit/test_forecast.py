# apex-quant/tests/unit/test_forecast.py
"""Unit tests for ForecastService probabilistic bands."""
import asyncio
import pytest
from apex.adapters.data.mock_adapter import MockAdapter
from apex.core.forecast import ForecastService
from apex.core.ingestion import DataQualityError
from apex.domain.enums import Timeframe
from apex.domain.models import Bar, Forecast


def test_forecast_generates_valid_probabilistic_bands():
    adapter = MockAdapter(base_price=2450.0)
    bars = asyncio.run(adapter.get_ohlcv("RELIANCE.NS", Timeframe.M15, 30))
    
    svc = ForecastService()
    fc = svc.generate_forecast(bars, horizon_bars=12)

    assert isinstance(fc, Forecast)
    assert fc.symbol == "RELIANCE.NS"
    assert fc.horizon_bars == 12
    assert 0.0 <= fc.directional_prob <= 1.0

    # Sanity checks on range bands
    assert fc.high_band[0] <= fc.high_band[1]
    assert fc.low_band[0] <= fc.low_band[1]
    assert fc.low_band[1] < fc.high_band[0]


def test_forecast_rejects_unclosed_candle():
    adapter = MockAdapter(base_price=2450.0)
    bars = list(asyncio.run(adapter.get_ohlcv("RELIANCE.NS", Timeframe.M15, 25)))
    
    corrupted_bar = Bar(
        symbol=bars[-1].symbol,
        timeframe=bars[-1].timeframe,
        timestamp=bars[-1].timestamp,
        open=bars[-1].open,
        high=bars[-1].high,
        low=bars[-1].low,
        close=bars[-1].close,
        volume=bars[-1].volume,
        is_closed=False,
    )
    bars[-1] = corrupted_bar

    svc = ForecastService()
    with pytest.raises(DataQualityError, match="Causality Violation"):
        svc.generate_forecast(bars)


def test_forecast_rejects_insufficient_history():
    adapter = MockAdapter(base_price=2450.0)
    bars = asyncio.run(adapter.get_ohlcv("RELIANCE.NS", Timeframe.M15, 10))
    svc = ForecastService()
    with pytest.raises(DataQualityError, match="Insufficient history"):
        svc.generate_forecast(bars)

# apex-quant/tests/unit/test_features.py
"""Unit tests for FeatureService calculations and pattern detection."""
import asyncio
from datetime import datetime, timedelta
import pytest
from apex.adapters.data.mock_adapter import MockAdapter
from apex.core.features import FeatureService
from apex.core.ingestion import DataQualityError
from apex.domain.enums import Timeframe
from apex.domain.models import Bar


def test_feature_computation_outputs_complete_snapshot():
    adapter = MockAdapter(base_price=2480.0)
    bars = asyncio.run(adapter.get_ohlcv("TCS.NS", Timeframe.M15, 30))
    snapshot = FeatureService.compute(bars)

    assert snapshot.symbol == "TCS.NS"
    assert snapshot.spot_price > 0
    assert "ema_20" in snapshot.indicators
    assert "rsi_14" in snapshot.indicators
    assert "atr_14" in snapshot.indicators
    assert "vwap" in snapshot.indicators
    assert "atr_tolerance" in snapshot.indicators
    assert 0.0 <= snapshot.confluence_score <= 100.0


def test_insufficient_bars_raises_error():
    adapter = MockAdapter()
    bars = asyncio.run(adapter.get_ohlcv("TCS.NS", Timeframe.M15, 10))
    with pytest.raises(DataQualityError, match="Insufficient history"):
        FeatureService.compute(bars)


def test_hammer_pattern_detection():
    # Build 20 neutral bars followed by a pristine hammer
    base_ts = datetime(2026, 10, 23, 10, 0)
    bars = [
        Bar(
            symbol="TEST.NS",
            timeframe=Timeframe.M15,
            timestamp=base_ts + timedelta(minutes=15 * i),
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.0,
            volume=10000.0,
            is_closed=True,
        )
        for i in range(25)
    ]
    # Add hammer candle: open=100, close=100.5 (body 0.5), low=98.5 (lower shadow 1.5 >= 2*body), high=100.55
    bars.append(
        Bar(
            symbol="TEST.NS",
            timeframe=Timeframe.M15,
            timestamp=base_ts + timedelta(minutes=15 * 25),
            open=100.0,
            high=100.55,
            low=98.50,
            close=100.50,
            volume=25000.0,
            is_closed=True,
        )
    )
    snapshot = FeatureService.compute(bars)
    assert "HAMMER" in snapshot.patterns

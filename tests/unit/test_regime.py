# apex-quant/tests/unit/test_regime.py
"""Unit tests for RegimeClassifier and Volatility Gating."""
import asyncio
from datetime import datetime, timedelta
import pytest
from apex.adapters.data.mock_adapter import MockAdapter
from apex.core.regime import RegimeClassifier
from apex.domain.enums import MarketRegime, Timeframe
from apex.domain.models import Bar


def test_volatility_gate_calm_market_returns_one():
    adapter = MockAdapter(base_price=1500.0)
    bars = asyncio.run(adapter.get_ohlcv("INFY.NS", Timeframe.M15, 30))
    
    gate = RegimeClassifier.compute_volatility_gate(bars, baseline_annual_vol=20.0)
    assert gate == 1.0


def test_volatility_gate_spikes_down_in_crisis():
    base_ts = datetime(2026, 10, 23, 10, 0)
    # Generate volatile series with large random swings (10% jumps)
    bars = []
    price = 1000.0
    for i in range(30):
        price = price * (1.10 if i % 2 == 0 else 0.90)
        bars.append(
            Bar(
                symbol="CRISIS.NS",
                timeframe=Timeframe.M15,
                timestamp=base_ts + timedelta(minutes=15 * i),
                open=price,
                high=price * 1.05,
                low=price * 0.95,
                close=price,
                volume=50000.0,
                is_closed=True,
            )
        )
    
    gate = RegimeClassifier.compute_volatility_gate(bars, baseline_annual_vol=15.0)
    assert gate < 1.0
    assert gate >= 0.20


def test_regime_classification_expansion_and_turbulence():
    adapter = MockAdapter(base_price=2500.0)
    bars = asyncio.run(adapter.get_ohlcv("RELIANCE.NS", Timeframe.M15, 30))
    
    regime = RegimeClassifier.classify_regime(bars)
    assert isinstance(regime, MarketRegime)


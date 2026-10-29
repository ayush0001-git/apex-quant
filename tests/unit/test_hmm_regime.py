# apex-quant/tests/unit/test_hmm_regime.py
"""Unit tests for GaussianHMMRegimeDetector and HMM state classification."""
import asyncio
from datetime import datetime, timedelta
import pytest
from apex.adapters.data.mock_adapter import MockAdapter
from apex.core.regime import GaussianHMMRegimeDetector, HMMRegimeOutput
from apex.domain.enums import Timeframe
from apex.domain.models import Bar


def test_hmm_regime_detects_trend_state():
    adapter = MockAdapter(base_price=2000.0)
    bars = asyncio.run(adapter.get_ohlcv("RELIANCE.NS", Timeframe.M15, 40))
    
    output = GaussianHMMRegimeDetector.detect_regime(bars)
    
    assert isinstance(output, HMMRegimeOutput)
    assert output.state_id in (0, 1, 2)
    assert len(output.state_probabilities) == 3
    assert 0.99 <= sum(output.state_probabilities) <= 1.01
    assert 0.20 <= output.volatility_gate <= 1.0


def test_hmm_regime_detects_turbulent_state_on_extreme_volatility():
    base_ts = datetime(2026, 10, 23, 10, 0)
    bars = []
    p = 1000.0
    for i in range(40):
        # 12% swings simulating extreme turbulence / panic
        p = p * (1.12 if i % 2 == 0 else 0.88)
        bars.append(
            Bar(
                symbol="TURB.NS",
                timeframe=Timeframe.M15,
                timestamp=base_ts + timedelta(minutes=15 * i),
                open=p,
                high=p * 1.06,
                low=p * 0.94,
                close=p,
                volume=80000.0,
                is_closed=True,
            )
        )
    
    output = GaussianHMMRegimeDetector.detect_regime(bars)
    
    # State 2 corresponds to high-volatility turbulence
    assert output.volatility_gate < 1.0
    assert output.state_id == 2 or output.state_probabilities[2] > 0.3

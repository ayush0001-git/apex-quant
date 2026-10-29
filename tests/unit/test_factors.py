# apex-quant/tests/unit/test_factors.py
"""Unit tests for FactorService."""
import asyncio
from datetime import datetime, timedelta
import pytest
from apex.adapters.data.mock_adapter import MockAdapter
from apex.core.factors import FactorService
from apex.core.ingestion import DataQualityError
from apex.domain.enums import Timeframe
from apex.domain.models import Bar


def test_factor_service_computes_single_asset_factors():
    adapter = MockAdapter(base_price=2000.0)
    bars = asyncio.run(adapter.get_ohlcv("RELIANCE.NS", Timeframe.M15, 30))
    
    factors = FactorService.compute_single_asset_factors(bars)
    
    assert "momentum_20d" in factors
    assert "reversal_5d" in factors
    assert "realized_vol_20d" in factors
    assert "atr_price_ratio" in factors
    assert "volume_zscore_20d" in factors
    assert "amihud_illiquidity" in factors
    assert "quality_score" in factors
    assert factors["quality_score"] >= 0.0


def test_factor_service_cross_sectional_normalization():
    # Synthetic factor exposures across 4 instruments
    universe_factors = {
        "RELIANCE.NS": {
            "momentum_20d": 10.5,
            "reversal_5d": -1.2,
            "realized_vol_20d": 15.0,
            "atr_price_ratio": 1.2,
            "volume_zscore_20d": 1.8,
            "amihud_illiquidity": 0.002,
            "quality_score": 8.0,
        },
        "TCS.NS": {
            "momentum_20d": 2.1,
            "reversal_5d": 0.5,
            "realized_vol_20d": 12.0,
            "atr_price_ratio": 1.0,
            "volume_zscore_20d": -0.5,
            "amihud_illiquidity": 0.001,
            "quality_score": 7.5,
        },
        "INFY.NS": {
            "momentum_20d": -5.4,
            "reversal_5d": 2.0,
            "realized_vol_20d": 22.0,
            "atr_price_ratio": 1.8,
            "volume_zscore_20d": 0.2,
            "amihud_illiquidity": 0.003,
            "quality_score": 5.0,
        },
    }
    
    scores = FactorService.compute_cross_sectional_scores(universe_factors)
    
    assert len(scores) == 3
    # RELIANCE has top momentum and high quality -> should lead composite score
    assert scores["RELIANCE.NS"].composite_alpha_score > scores["INFY.NS"].composite_alpha_score
    assert -100.0 <= scores["RELIANCE.NS"].composite_alpha_score <= 100.0


def test_factor_service_rejects_unclosed_bars():
    base_ts = datetime(2026, 10, 23, 10, 0)
    bars = [
        Bar("TEST.NS", Timeframe.M15, base_ts + timedelta(minutes=15 * i), 100, 101, 99, 100, 1000, True)
        for i in range(25)
    ]
    bars[-1] = Bar("TEST.NS", Timeframe.M15, base_ts + timedelta(minutes=15 * 25), 100, 101, 99, 100, 1000, False)
    
    with pytest.raises(DataQualityError, match="Causality Violation"):
        FactorService.compute_single_asset_factors(bars)


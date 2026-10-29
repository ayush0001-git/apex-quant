# apex-quant/tests/unit/test_dynamic_slippage.py
"""Unit tests for DynamicSlippageModel."""
import pytest
from apex.core.slippage import DynamicSlippageModel
from apex.domain.config import Settings


def test_dynamic_slippage_baseline():
    settings = Settings.load()
    model = DynamicSlippageModel(settings.friction)
    
    # Calm market conditions
    quote = model.estimate_slippage(
        turnover=100000.0,
        shares=100,
        spot_price=1000.0,
        volume_ratio=1.0,
        volatility_pct=0.015,
    )
    
    assert quote.slippage_bps >= 4.5
    assert quote.slippage_bps <= 6.0
    assert quote.slippage_inr > 0.0


def test_dynamic_slippage_expands_on_volatility_spike():
    settings = Settings.load()
    model = DynamicSlippageModel(settings.friction)
    
    calm_quote = model.estimate_slippage(
        turnover=100000.0,
        shares=100,
        spot_price=1000.0,
        volume_ratio=1.0,
        volatility_pct=0.015,
    )
    
    # High volatility spike (3x normal volatility)
    spike_quote = model.estimate_slippage(
        turnover=100000.0,
        shares=100,
        spot_price=1000.0,
        volume_ratio=1.0,
        volatility_pct=0.045,
    )
    
    assert spike_quote.slippage_bps > calm_quote.slippage_bps
    assert spike_quote.volatility_penalty_bps > 0.0


def test_dynamic_slippage_expands_on_thin_volume():
    settings = Settings.load()
    model = DynamicSlippageModel(settings.friction)
    
    normal_quote = model.estimate_slippage(
        turnover=100000.0,
        shares=100,
        spot_price=1000.0,
        volume_ratio=1.0,
    )
    
    # Illiquid / thin volume bar (0.2x normal volume)
    thin_quote = model.estimate_slippage(
        turnover=100000.0,
        shares=100,
        spot_price=1000.0,
        volume_ratio=0.2,
    )
    
    assert thin_quote.slippage_bps > normal_quote.slippage_bps


def test_dynamic_slippage_clamped_within_bounds():
    settings = Settings.load()
    model = DynamicSlippageModel(settings.friction)
    
    # Extreme conditions
    extreme_quote = model.estimate_slippage(
        turnover=50000000.0,
        shares=50000,
        spot_price=1000.0,
        volume_ratio=5.0,
        volatility_pct=0.10,
    )
    
    max_allowed_bps = settings.friction.max_slippage_pct * 10000
    min_allowed_bps = settings.friction.min_slippage_pct * 10000
    assert extreme_quote.slippage_bps <= max_allowed_bps
    assert extreme_quote.slippage_bps >= min_allowed_bps


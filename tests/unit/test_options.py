# apex-quant/tests/unit/test_options.py
"""Unit tests for OptionsAnalyticsEngine (Black-Scholes, Greeks, IV, Max Pain, GEX)."""
import pytest
from apex.core.options import OptionsAnalyticsEngine, OptionsChainSnapshot


def test_black_scholes_pricing_and_greeks():
    engine = OptionsAnalyticsEngine()
    spot = 2500.0
    strike = 2500.0  # ATM
    t_years = 30.0 / 365.0
    iv = 0.20
    
    c_price = engine.black_scholes_price(spot, strike, t_years, iv, is_call=True)
    p_price = engine.black_scholes_price(spot, strike, t_years, iv, is_call=False)
    
    assert c_price > 0.0
    assert p_price > 0.0
    
    c_greeks = engine.calculate_greeks(spot, strike, t_years, iv, is_call=True)
    assert 0.40 <= c_greeks["delta"] <= 0.60
    assert c_greeks["gamma"] > 0.0
    assert c_greeks["vega"] > 0.0
    assert c_greeks["theta"] < 0.0  # Time decay is negative


def test_options_implied_volatility_solver():
    engine = OptionsAnalyticsEngine()
    spot = 2000.0
    strike = 2000.0
    t_years = 15.0 / 365.0
    known_iv = 0.22
    
    market_price = engine.black_scholes_price(spot, strike, t_years, known_iv, is_call=True)
    # Standard decimal return (F18)
    solved_iv_decimal = engine.solve_implied_volatility(market_price, spot, strike, t_years, is_call=True)
    assert abs(solved_iv_decimal - known_iv) < 0.005

    # Explicit percentage return
    solved_iv_pct = engine.solve_implied_volatility(market_price, spot, strike, t_years, is_call=True, as_percentage=True)
    assert abs(solved_iv_pct - (known_iv * 100.0)) < 0.5


def test_synthetic_options_chain_analysis():
    engine = OptionsAnalyticsEngine()
    chain = engine.generate_synthetic_chain("NIFTY.NS", spot=24000.0, num_strikes=11)
    
    assert isinstance(chain, OptionsChainSnapshot)
    assert chain.symbol == "NIFTY.NS"
    assert chain.pcr_open_interest > 0.0
    assert chain.pcr_volume > 0.0
    assert 23500.0 <= chain.max_pain_strike <= 24500.0
    assert len(chain.contracts) == 22  # 11 strikes * 2 (CE + PE)


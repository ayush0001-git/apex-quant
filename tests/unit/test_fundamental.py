# apex-quant/tests/unit/test_fundamental.py
"""Unit tests for FundamentalAdapter and quality factor ingestion."""
import pytest
from apex.adapters.data.fundamental_adapter import FundamentalAdapter, FundamentalSnapshot


def test_fundamental_adapter_fetches_known_symbol():
    adapter = FundamentalAdapter()
    snap = adapter.get_fundamentals("RELIANCE.NS")
    
    assert isinstance(snap, FundamentalSnapshot)
    assert snap.symbol == "RELIANCE.NS"
    assert snap.piotroski_score >= 7
    assert snap.ev_to_ebitda > 0.0
    assert snap.pe_ratio > 0.0
    assert snap.roe_pct > 0.0
    assert snap.fii_holding_pct > 10.0
    assert snap.quality_composite >= 50.0


def test_fundamental_adapter_neutral_fallback():
    adapter = FundamentalAdapter()
    snap = adapter.get_fundamentals("UNKNOWN_TICKER.NS")
    
    assert snap.symbol == "UNKNOWN_TICKER.NS"
    assert snap.piotroski_score == 6
    assert snap.quality_composite > 0.0


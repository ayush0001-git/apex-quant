# apex-quant/tests/contract/test_llm_port.py
"""Contract tests asserting LLMPort two-tier separation rules."""
import asyncio
from datetime import datetime
import pytest
from apex.adapters.llm.free_pool import FreePoolAdapter
from apex.adapters.llm.paid_gate import PaidGateAdapter
from apex.domain.enums import MarketRegime
from apex.domain.models import FeatureSnapshot, Forecast


def make_dummy_features() -> FeatureSnapshot:
    return FeatureSnapshot(
        symbol="TCS.NS",
        timestamp=datetime(2026, 10, 23, 15, 0),
        spot_price=3850.0,
        indicators={"atr_14": 40.0},
        patterns=(),
        confluence_score=70.0,
        volume_ratio=1.4,
        regime=MarketRegime.BULL_EXPANSION,
    )


def test_free_pool_cannot_synthesize():
    """Verify architectural firewall: Free pool must reject synthesize calls."""
    pool = FreePoolAdapter()
    features = make_dummy_features()
    with pytest.raises(NotImplementedError, match="strictly prohibited from executing synthesize"):
        asyncio.run(pool.synthesize("TCS.NS", features, None))


def test_paid_gate_cannot_scan_batch():
    gate = PaidGateAdapter()
    with pytest.raises(NotImplementedError, match="reserved for synthesis"):
        asyncio.run(gate.scan_batch(["TCS.NS"]))


def test_paid_gate_synthesize_success():
    gate = PaidGateAdapter()
    features = make_dummy_features()
    forecast = Forecast(
        symbol="TCS.NS",
        horizon_bars=12,
        high_band=(3900.0, 3950.0),
        low_band=(3820.0, 3840.0),
        directional_prob=0.65,
    )
    result = asyncio.run(gate.synthesize("TCS.NS", features, forecast))
    assert result is not None
    assert result.action.value in ["LONG", "SHORT", "HOLD"]

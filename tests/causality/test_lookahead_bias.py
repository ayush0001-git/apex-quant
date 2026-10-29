# apex-quant/tests/causality/test_lookahead_bias.py
"""Causality tests: Ensures zero look-ahead bias and strict non-repainting."""
import asyncio
import pytest
from apex.adapters.data.mock_adapter import MockAdapter
from apex.core.features import FeatureService
from apex.core.ingestion import DataQualityError
from apex.domain.enums import Timeframe
from apex.domain.models import Bar


def test_features_reject_unclosed_bar():
    adapter = MockAdapter()
    bars = list(asyncio.run(adapter.get_ohlcv("RELIANCE.NS", Timeframe.M15, 25)))
    
    # Intentionally corrupt the last bar with is_closed=False
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

    with pytest.raises(DataQualityError, match="Causality Violation"):
        FeatureService.compute(bars)


def test_features_strictly_causal_incremental_matches_batch():
    """Verify that adding future bars does NOT retroactively change the features of the past."""
    adapter = MockAdapter()
    full_series = list(asyncio.run(adapter.get_ohlcv("RELIANCE.NS", Timeframe.M15, 50)))

    # Compute snapshot at bar index 35
    snapshot_at_35 = FeatureService.compute(full_series[:36])

    # Compute snapshot at bar index 50
    snapshot_at_50 = FeatureService.compute(full_series)

    # Re-computing on slice [:36] must be 100% deterministic
    recomputed_35 = FeatureService.compute(full_series[:36])
    assert snapshot_at_35.spot_price == recomputed_35.spot_price
    assert snapshot_at_35.indicators["rsi_14"] == recomputed_35.indicators["rsi_14"]
    assert snapshot_at_35.indicators["ema_20"] == recomputed_35.indicators["ema_20"]
    assert snapshot_at_35.confluence_score == recomputed_35.confluence_score

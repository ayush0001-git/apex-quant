# apex-quant/tests/unit/test_ingestion.py
"""Unit tests for IngestionService validation and causality filters."""
from datetime import datetime, timedelta
import pytest
from apex.core.ingestion import IngestionService, DataQualityError
from apex.domain.enums import Timeframe
from apex.domain.models import Bar


def make_valid_bar(idx: int, is_closed: bool = True, volume: float = 1000.0) -> Bar:
    ts = datetime(2026, 10, 23, 10, 0) + timedelta(minutes=15 * idx)
    return Bar(
        symbol="NIFTY.NS",
        timeframe=Timeframe.M15,
        timestamp=ts,
        open=24800.0,
        high=24850.0,
        low=24790.0,
        close=24830.0,
        volume=volume,
        is_closed=is_closed,
    )


def test_ingestion_accepts_clean_sequence():
    bars = [make_valid_bar(i) for i in range(5)]
    validated = IngestionService.validate_and_normalize(bars)
    assert len(validated) == 5


def test_ingestion_rejects_unclosed_candle():
    """Causality test: is_closed=False must raise DataQualityError."""
    bars = [make_valid_bar(0), make_valid_bar(1), make_valid_bar(2, is_closed=False)]
    with pytest.raises(DataQualityError, match="Causality Violation"):
        IngestionService.validate_and_normalize(bars)


def test_ingestion_rejects_zero_volume():
    bars = [make_valid_bar(0), make_valid_bar(1, volume=0.0)]
    with pytest.raises(DataQualityError, match="Dead Market Bar"):
        IngestionService.validate_and_normalize(bars)

# apex-quant/tests/unit/test_data_quality.py
"""Unit tests for Data Quality & Corporate Action Reconciler."""
from datetime import datetime, timedelta
from apex.adapters.data.data_quality import DataQualityReconciler
from apex.domain.models import Bar
from apex.domain.enums import Timeframe


def test_data_quality_clean_series():
    now = datetime.now()
    bars = [
        Bar(
            symbol="RELIANCE.NS",
            timeframe=Timeframe.M15,
            timestamp=now + timedelta(minutes=15 * i),
            open=2500.0 + i,
            high=2505.0 + i,
            low=2495.0 + i,
            close=2502.0 + i,
            volume=10000.0 + i * 50,
            is_closed=True,
        )
        for i in range(30)
    ]

    report = DataQualityReconciler.validate_series(bars)
    assert report.is_valid is True
    assert report.total_bars == 30
    assert report.stale_bars_count == 0
    assert report.corporate_action_suspected is False


def test_data_quality_detects_stock_split():
    now = datetime.now()
    bars = []
    # Normal bars around 2000 INR
    for i in range(15):
        bars.append(
            Bar(
                symbol="TCS.NS",
                timeframe=Timeframe.D1,
                timestamp=now + timedelta(days=i),
                open=2000.0,
                high=2020.0,
                low=1990.0,
                close=2010.0,
                volume=100000.0,
                is_closed=True,
            )
        )
    # Overnight 2:1 stock split jump (price drops from 2010 to 1005)
    bars.append(
        Bar(
            symbol="TCS.NS",
            timeframe=Timeframe.D1,
            timestamp=now + timedelta(days=15),
            open=1005.0,
            high=1020.0,
            low=1000.0,
            close=1015.0,
            volume=200000.0,
            is_closed=True,
        )
    )

    report = DataQualityReconciler.validate_series(bars)
    assert report.corporate_action_suspected is True
    assert report.suspected_split_ratio == "2:1 Stock Split / Bonus"


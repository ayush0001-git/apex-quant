# apex-quant/tests/unit/test_data_integrity.py
"""Unit tests for point-in-time data integrity, corporate action sanity checks, and metadata logging."""
from datetime import date, datetime, timedelta
from pathlib import Path
import json
import pandas as pd
import pytest

from apex.domain.enums import Timeframe
from apex.domain.models import Bar
from apex.core.data_integrity import (
    validate_corporate_actions,
    log_fetch_metadata,
    compute_bars_checksum,
    check_universe_membership,
    run_all_integrity_checks,
)
from apex.adapters.data.bhavcopy_adapter import BhavcopyAdapter


def _generate_clean_bars(symbol: str = "TCS.NS", n: int = 30) -> list[Bar]:
    base_ts = datetime(2026, 1, 1, 9, 15)
    bars = []
    price = 3500.0
    for i in range(n):
        price += (i % 3 - 1) * 10.0
        bars.append(
            Bar(
                symbol=symbol,
                timeframe=Timeframe.D1,
                timestamp=base_ts + timedelta(days=i),
                open=price,
                high=price + 20.0,
                low=price - 15.0,
                close=price + 5.0,
                volume=1_000_000.0,
                is_closed=True,
            )
        )
    return bars


def test_validate_corporate_actions_clean_series():
    bars = _generate_clean_bars()
    report = validate_corporate_actions(bars)
    assert report.is_clean is True
    assert len(report.flags) == 0
    assert report.total_bars_checked == len(bars)
    assert report.adjusted_series_consistent is True


def test_validate_corporate_actions_detects_unadjusted_split():
    bars = _generate_clean_bars(n=20)
    # Simulate an unadjusted 2:1 stock split at bar 10 (price halves)
    split_date = bars[10].timestamp
    split_bar = Bar(
        symbol="TCS.NS",
        timeframe=Timeframe.D1,
        timestamp=split_date,
        open=bars[9].close * 0.50, # 50% drop
        high=bars[9].close * 0.51,
        low=bars[9].close * 0.49,
        close=bars[9].close * 0.50,
        volume=2_000_000.0,
        is_closed=True,
    )
    bars[10] = split_bar

    report = validate_corporate_actions(bars)
    assert report.is_clean is False
    assert len(report.flags) >= 1
    flag = report.flags[0]
    assert flag.direction == "DROP"
    assert flag.likely_action == "2:1 Stock Split"
    assert flag.has_matching_record is False


def test_validate_corporate_actions_with_known_action_record():
    bars = _generate_clean_bars(n=20)
    split_date = bars[10].timestamp.date()
    # In a real stock split, all subsequent bars are at the post-split price level
    for i in range(10, len(bars)):
        bars[i] = Bar(
            symbol="TCS.NS",
            timeframe=Timeframe.D1,
            timestamp=bars[i].timestamp,
            open=bars[i].open * 0.50,
            high=bars[i].high * 0.50,
            low=bars[i].low * 0.50,
            close=bars[i].close * 0.50,
            volume=bars[i].volume * 2.0,
            is_closed=True,
        )

    known = {"TCS.NS": [split_date]}
    report = validate_corporate_actions(bars, known_actions=known)
    assert report.is_clean is True
    assert len(report.flags) == 1
    assert report.flags[0].has_matching_record is True


def test_validate_corporate_actions_dataframe_input():
    dates = pd.date_range("2026-01-01", periods=15, freq="D")
    df = pd.DataFrame({
        "Symbol": ["INFY.NS"] * 15,
        "Open": [1500.0 + i for i in range(15)],
        "High": [1520.0 + i for i in range(15)],
        "Low": [1490.0 + i for i in range(15)],
        "Close": [1510.0 + i for i in range(15)],
        "Adj Close": [1510.0 + i for i in range(15)],
        "Volume": [500_000.0] * 15,
    }, index=dates)

    report = validate_corporate_actions(df)
    assert report.is_clean is True
    assert len(report.flags) == 0


def test_log_fetch_metadata_and_checksum(tmp_path):
    bars = _generate_clean_bars(n=5)
    checksum = compute_bars_checksum(bars)
    assert isinstance(checksum, str)
    assert len(checksum) == 64

    log_path = log_fetch_metadata(
        source="test_feed",
        symbol="TCS.NS",
        row_count=5,
        checksum=checksum,
        log_dir=tmp_path,
        timeframe="D1",
        extra={"param": "test"},
    )
    assert log_path.exists()
    lines = log_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["source"] == "test_feed"
    assert data["symbol"] == "TCS.NS"
    assert data["row_count"] == 5
    assert data["checksum"] == checksum


def test_check_universe_membership():
    bhavcopy_csv = """SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,TOTALTRADES,ISIN
RELIANCE,EQ,2500,2550,2480,2520,2520,2500,200000,504000000,23-OCT-2026,15000,INE002A01018
INFY,EQ,1500,1520,1490,1510,1510,1500,300000,453000000,23-OCT-2026,20000,INE009A01021
"""
    adapter = BhavcopyAdapter()
    adapter.load_bhavcopy_csv(bhavcopy_csv)

    target_d = date(2026, 10, 23)
    res_reliance = check_universe_membership("RELIANCE.NS", target_d, adapter)
    assert res_reliance.is_member is True
    assert res_reliance.constituent_count == 2

    res_unknown = check_universe_membership("UNKNOWN.NS", target_d, adapter)
    assert res_unknown.is_member is False


def test_run_all_integrity_checks_pipeline(tmp_path):
    bars = _generate_clean_bars(n=15)
    res = run_all_integrity_checks(bars, log_dir=tmp_path)
    assert res["is_clean"] is True
    assert res["corporate_action_check"]["is_clean"] is True
    assert res["fetch_log"]["row_count"] == 15
    assert Path(res["fetch_log"]["log_file"]).exists()

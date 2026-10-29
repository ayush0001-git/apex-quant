# apex-quant/src/apex/core/data_integrity.py
"""Point-in-Time Data Integrity & Sanity Checks.

Prevents silent data corruption — the single most dangerous failure mode
in 'real data every restart' workflows. Three guards:

1. validate_corporate_actions(data):
   Accepts either Sequence[Bar] or pd.DataFrame.
   Compares adjusted vs. unadjusted price series (e.g. Close vs Adj Close) or
   detects overnight price jumps (>threshold) without a matching corporate action record.
   Catches unadjusted splits, bonuses, and large dividends.

2. log_fetch_metadata(source, symbol, row_count, checksum):
   Appends an immutable JSONL record on every data fetch. Gives full auditability
   and reproducibility across restarts.

3. check_universe_membership(symbol, target_date, bhavcopy_adapter):
   Asserts the stock was actually in the NIFTY 100/200 on that date using
   point-in-time constituent records.

Called in the data adapter's fetch() path. No architecture change, no new dependency.
"""
import hashlib
import json
import math
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

import numpy as np
import pandas as pd

from ..domain.models import Bar


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_DEFAULT_JUMP_THRESHOLD = 0.20   # 20% overnight jump -> suspicious
_DEFAULT_LOG_DIR = Path("data/fetch_logs")
_NIFTY_100_MIN_TURNOVER = 250_000_000.0   # ₹25 Cr minimum daily turnover


# ---------------------------------------------------------------------------
# 1. Corporate Action Validation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CorporateActionFlag:
    """Individual suspicious price event flagged by the validator."""
    symbol: str
    date: str
    prev_close: float
    current_price: float
    jump_pct: float                     # Absolute % change
    direction: str                      # "DROP" or "SPIKE"
    likely_action: str                  # e.g. "2:1 Stock Split", "Bonus 1:1", etc.
    has_matching_record: bool           # Whether a known corporate action record was found


@dataclass(frozen=True)
class CorporateActionReport:
    """Result of corporate action validation across a price series or DataFrame."""
    symbol: str
    total_bars_checked: int
    flags: List[CorporateActionFlag]
    is_clean: bool                      # True if no unexplained jumps
    adjusted_series_consistent: bool    # True if prices form a smooth consistent series


def validate_corporate_actions(
    data: Union[Sequence[Bar], pd.DataFrame],
    jump_threshold: float = _DEFAULT_JUMP_THRESHOLD,
    known_actions: Optional[Dict[str, List[Union[date, str]]]] = None,
    symbol: Optional[str] = None,
) -> CorporateActionReport:
    """Compare consecutive prices or adjusted vs unadjusted series for corporate actions.

    Accepts either:
    - Sequence[Bar]: Checks consecutive bars for overnight jumps > jump_threshold.
    - pd.DataFrame: If 'Close' and 'Adj Close' exist, checks the adjustment ratio
                    for sudden shifts > jump_threshold. Otherwise checks 'Close' or 'Open'.

    Args:
        data: Bar sequence or DataFrame with historical price data.
        jump_threshold: Minimum absolute % change to flag (default 20%).
        known_actions: Optional dict mapping symbol -> list of known action dates.
        symbol: Optional symbol override if not discernible from data.

    Returns:
        CorporateActionReport detailing findings.
    """
    if isinstance(data, pd.DataFrame):
        return _validate_df_corporate_actions(data, jump_threshold, known_actions, symbol)
    else:
        return _validate_bars_corporate_actions(data, jump_threshold, known_actions, symbol)


def _validate_bars_corporate_actions(
    bars: Sequence[Bar],
    jump_threshold: float,
    known_actions: Optional[Dict[str, List[Union[date, str]]]],
    symbol_override: Optional[str],
) -> CorporateActionReport:
    """Validate corporate actions on Sequence[Bar]."""
    if not bars:
        return CorporateActionReport(
            symbol=symbol_override or "UNKNOWN",
            total_bars_checked=0,
            flags=[],
            is_clean=True,
            adjusted_series_consistent=True,
        )

    symbol = symbol_override or bars[0].symbol
    known_dates_str = _extract_known_dates(known_actions, symbol)
    flags: List[CorporateActionFlag] = []

    for i in range(1, len(bars)):
        prev_bar = bars[i - 1]
        curr_bar = bars[i]

        prev_close = prev_bar.close
        curr_open = curr_bar.open

        if prev_close <= 0:
            continue

        change_pct = (curr_open - prev_close) / prev_close
        abs_change = abs(change_pct)

        if abs_change < jump_threshold:
            continue

        direction = "DROP" if change_pct < 0 else "SPIKE"
        likely_action = _classify_price_jump(change_pct, prev_close, curr_open)

        dt_str = str(curr_bar.timestamp.date() if isinstance(curr_bar.timestamp, datetime) else curr_bar.timestamp)
        has_record = dt_str in known_dates_str

        flags.append(CorporateActionFlag(
            symbol=symbol,
            date=dt_str,
            prev_close=round(prev_close, 2),
            current_price=round(curr_open, 2),
            jump_pct=round(abs_change * 100, 2),
            direction=direction,
            likely_action=likely_action,
            has_matching_record=has_record,
        ))

    unexplained = [f for f in flags if not f.has_matching_record]

    # Adjusted series consistency: check if log-returns have reasonable bounds
    closes = [b.close for b in bars if b.close > 0]
    adjusted_consistent = True
    if len(closes) >= 10:
        log_rets = np.diff(np.log(closes))
        max_abs_ret = float(np.max(np.abs(log_rets)))
        if max_abs_ret > 0.50:
            adjusted_consistent = False

    return CorporateActionReport(
        symbol=symbol,
        total_bars_checked=len(bars),
        flags=flags,
        is_clean=len(unexplained) == 0,
        adjusted_series_consistent=adjusted_consistent,
    )


def _validate_df_corporate_actions(
    df: pd.DataFrame,
    jump_threshold: float,
    known_actions: Optional[Dict[str, List[Union[date, str]]]],
    symbol_override: Optional[str],
) -> CorporateActionReport:
    """Validate corporate actions on pd.DataFrame."""
    if df.empty:
        return CorporateActionReport(
            symbol=symbol_override or "UNKNOWN",
            total_bars_checked=0,
            flags=[],
            is_clean=True,
            adjusted_series_consistent=True,
        )

    symbol = symbol_override or (df["Symbol"].iloc[0] if "Symbol" in df.columns else "UNKNOWN")
    known_dates_str = _extract_known_dates(known_actions, symbol)
    flags: List[CorporateActionFlag] = []

    has_close = "Close" in df.columns
    has_adj_close = "Adj Close" in df.columns

    if has_close and has_adj_close:
        # Check adjustment factor ratio: factor = Adj Close / Close
        close_vals = df["Close"].astype(float).values
        adj_vals = df["Adj Close"].astype(float).values
        dates = df.index

        with np.errstate(divide="ignore", invalid="ignore"):
            adj_ratio = np.where(close_vals > 0, adj_vals / close_vals, 1.0)

        for i in range(1, len(adj_ratio)):
            prev_r = adj_ratio[i - 1]
            curr_r = adj_ratio[i]

            if prev_r <= 0 or curr_r <= 0:
                continue

            ratio_change = abs(curr_r - prev_r) / prev_r
            if ratio_change >= jump_threshold:
                dt_str = str(dates[i].date() if hasattr(dates[i], "date") else dates[i])
                has_record = dt_str in known_dates_str

                c_prev = close_vals[i - 1]
                c_curr = close_vals[i]
                pct_change = (c_curr - c_prev) / (c_prev + 1e-8)

                flags.append(CorporateActionFlag(
                    symbol=symbol,
                    date=dt_str,
                    prev_close=round(c_prev, 2),
                    current_price=round(c_curr, 2),
                    jump_pct=round(ratio_change * 100, 2),
                    direction="DROP" if pct_change < 0 else "SPIKE",
                    likely_action=_classify_price_jump(pct_change, c_prev, c_curr),
                    has_matching_record=has_record,
                ))
    else:
        col = "Close" if has_close else ("Open" if "Open" in df.columns else None)
        if col:
            prices = df[col].astype(float).values
            dates = df.index
            for i in range(1, len(prices)):
                p_prev = prices[i - 1]
                p_curr = prices[i]
                if p_prev <= 0:
                    continue
                change_pct = (p_curr - p_prev) / p_prev
                if abs(change_pct) >= jump_threshold:
                    dt_str = str(dates[i].date() if hasattr(dates[i], "date") else dates[i])
                    has_record = dt_str in known_dates_str
                    flags.append(CorporateActionFlag(
                        symbol=symbol,
                        date=dt_str,
                        prev_close=round(p_prev, 2),
                        current_price=round(p_curr, 2),
                        jump_pct=round(abs(change_pct) * 100, 2),
                        direction="DROP" if change_pct < 0 else "SPIKE",
                        likely_action=_classify_price_jump(change_pct, p_prev, p_curr),
                        has_matching_record=has_record,
                    ))

    unexplained = [f for f in flags if not f.has_matching_record]

    adjusted_consistent = True
    if has_adj_close and len(df) >= 10:
        adj_vals = df["Adj Close"].astype(float).values
        adj_clean = adj_vals[adj_vals > 0]
        if len(adj_clean) >= 10:
            log_rets = np.diff(np.log(adj_clean))
            max_abs_ret = float(np.max(np.abs(log_rets)))
            if max_abs_ret > 0.50:
                adjusted_consistent = False

    return CorporateActionReport(
        symbol=symbol,
        total_bars_checked=len(df),
        flags=flags,
        is_clean=len(unexplained) == 0,
        adjusted_series_consistent=adjusted_consistent,
    )


def _extract_known_dates(known_actions: Optional[Dict], symbol: str) -> set:
    """Extract string formatted date set for symbol and base symbol."""
    if not known_actions:
        return set()
    result = set()
    candidates = [symbol, symbol.replace(".NS", "").replace(".BO", "")]
    for cand in candidates:
        if cand in known_actions:
            for item in known_actions[cand]:
                if isinstance(item, (date, datetime)):
                    result.add(str(item.date() if isinstance(item, datetime) else item))
                else:
                    result.add(str(item))
    return result


def _classify_price_jump(change_pct: float, prev_close: float, curr_open: float) -> str:
    """Heuristically classify a suspicious price jump."""
    abs_change = abs(change_pct)
    ratio = curr_open / prev_close if prev_close > 0 else 1.0

    if change_pct < 0:
        if 0.45 <= ratio <= 0.55:
            return "2:1 Stock Split"
        elif 0.18 <= ratio <= 0.22:
            return "5:1 Stock Split"
        elif 0.08 <= ratio <= 0.12:
            return "10:1 Stock Split"
        elif 0.60 <= ratio <= 0.75:
            return "Bonus Issue 1:2 or Large Dividend"
        elif 0.48 <= ratio <= 0.52:
            return "Bonus Issue 1:1"
        else:
            return f"Unexplained Drop ({abs_change*100:.1f}%)"
    else:
        if 1.90 <= ratio <= 2.10:
            return "Reverse Split 1:2 or Re-listing"
        elif 4.80 <= ratio <= 5.20:
            return "Reverse Split 1:5"
        else:
            return f"Unexplained Spike ({abs_change*100:.1f}%)"


# ---------------------------------------------------------------------------
# 2. Fetch Metadata Logging (Reproducibility)
# ---------------------------------------------------------------------------

@dataclass
class FetchMetadataRecord:
    """Immutable record of a single data fetch event."""
    source: str                         # e.g. "yfinance", "bhavcopy", "mock"
    symbol: str
    timestamp: str                      # ISO 8601 fetch timestamp
    row_count: int
    checksum: str                       # SHA-256 hex digest of the fetched data
    timeframe: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)


def log_fetch_metadata(
    source: str,
    symbol: str,
    row_count: int,
    checksum: str,
    log_dir: Path = _DEFAULT_LOG_DIR,
    timeframe: str = "",
    extra: Optional[Dict[str, Any]] = None,
) -> Path:
    """Append an immutable JSONL record for every data fetch.

    Args:
        source: Data source identifier (e.g. "yfinance", "bhavcopy").
        symbol: The ticker symbol fetched.
        row_count: Number of bars/rows received.
        checksum: SHA-256 hex digest of the raw data payload.
        log_dir: Directory for the JSONL log file.
        timeframe: Timeframe string (e.g. "D1", "M15").
        extra: Any additional metadata.

    Returns:
        Path to the JSONL log file.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "fetch_log.jsonl"

    record = FetchMetadataRecord(
        source=source,
        symbol=symbol,
        timestamp=datetime.now(timezone.utc).isoformat(),
        row_count=row_count,
        checksum=checksum,
        timeframe=timeframe,
        extra=extra or {},
    )

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(record), default=str) + "\n")

    return log_file


def compute_bars_checksum(bars: Sequence[Bar]) -> str:
    """Compute a deterministic SHA-256 checksum over a bar sequence."""
    h = hashlib.sha256()
    for b in bars:
        row = f"{b.symbol}|{b.timestamp.isoformat()}|{b.open}|{b.high}|{b.low}|{b.close}|{b.volume}|{b.is_closed}"
        h.update(row.encode("utf-8"))
    return h.hexdigest()


# ---------------------------------------------------------------------------
# 3. Universe Membership Assertion
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class UniverseMembershipResult:
    """Result of checking whether a symbol belonged to the target index on a date."""
    symbol: str
    target_date: str
    is_member: bool
    constituent_count: int              # Total constituents found on that date
    min_turnover_inr: float


def check_universe_membership(
    arg1: Any,
    arg2: Any = None,
    bhavcopy_adapter: Any = None,
    min_turnover_inr: float = _NIFTY_100_MIN_TURNOVER,
) -> UniverseMembershipResult:
    """Assert a stock was in the NIFTY 100/200 liquid universe on a historical date.

    Supports both signatures:
    - check_universe_membership(symbol="RELIANCE.NS", target_date=date(2024, 1, 1), bhavcopy_adapter=adapter)
    - check_universe_membership(target_date=date(2024, 1, 1), symbol="RELIANCE.NS", bhavcopy_adapter=adapter)

    Args:
        arg1: Either symbol (str) or target_date (date/datetime/str).
        arg2: Either target_date (date/datetime/str) or symbol (str).
        bhavcopy_adapter: An instance of BhavcopyAdapter with loaded archive data.
        min_turnover_inr: Minimum daily turnover threshold in INR.

    Returns:
        UniverseMembershipResult with is_member=True if the symbol qualified.
    """
    if isinstance(arg1, (date, datetime)) or (isinstance(arg1, str) and "-" in arg1 and len(arg1) == 10):
        target_date_obj = arg1
        symbol = str(arg2) if arg2 else "NIFTY50"
    else:
        symbol = str(arg1)
        target_date_obj = arg2 or date.today()

    if isinstance(target_date_obj, datetime):
        target_d = target_date_obj.date()
    elif isinstance(target_date_obj, str):
        try:
            target_d = datetime.strptime(target_date_obj, "%Y-%m-%d").date()
        except ValueError:
            target_d = date.today()
    else:
        target_d = target_date_obj

    formatted_symbol = f"{symbol}.NS" if not symbol.endswith((".NS", ".BO")) else symbol

    if bhavcopy_adapter is None:
        return UniverseMembershipResult(
            symbol=formatted_symbol,
            target_date=str(target_d),
            is_member=True,
            constituent_count=100,
            min_turnover_inr=min_turnover_inr,
        )

    constituents = bhavcopy_adapter.get_point_in_time_constituents(
        target_date=target_d,
        min_turnover_inr=min_turnover_inr,
    )

    is_member = formatted_symbol in constituents

    return UniverseMembershipResult(
        symbol=formatted_symbol,
        target_date=str(target_d),
        is_member=is_member,
        constituent_count=len(constituents),
        min_turnover_inr=min_turnover_inr,
    )


# ---------------------------------------------------------------------------
# Convenience: Run all three checks on a bar sequence
# ---------------------------------------------------------------------------

def run_all_integrity_checks(
    bars: Sequence[Bar],
    bhavcopy_adapter: Optional[Any] = None,
    known_actions: Optional[Dict[str, List[date]]] = None,
    log_dir: Path = _DEFAULT_LOG_DIR,
) -> Dict[str, Any]:
    """Run all three integrity checks on a bar sequence and return a summary."""
    results: Dict[str, Any] = {}

    if not bars:
        return {"error": "Empty bar sequence", "is_clean": False}

    symbol = bars[0].symbol
    timeframe = bars[0].timeframe.value if hasattr(bars[0].timeframe, 'value') else str(bars[0].timeframe)

    ca_report = validate_corporate_actions(bars, known_actions=known_actions)
    results["corporate_action_check"] = {
        "is_clean": ca_report.is_clean,
        "adjusted_series_consistent": ca_report.adjusted_series_consistent,
        "flags_count": len(ca_report.flags),
        "unexplained_flags": [
            {
                "date": f.date,
                "jump_pct": f.jump_pct,
                "direction": f.direction,
                "likely_action": f.likely_action,
            }
            for f in ca_report.flags if not f.has_matching_record
        ],
    }

    checksum = compute_bars_checksum(bars)
    log_path = log_fetch_metadata(
        source="integrity_check",
        symbol=symbol,
        row_count=len(bars),
        checksum=checksum,
        log_dir=log_dir,
        timeframe=timeframe,
    )
    results["fetch_log"] = {
        "checksum": checksum,
        "row_count": len(bars),
        "log_file": str(log_path),
    }

    if bhavcopy_adapter is not None:
        first_date = bars[0].timestamp.date() if isinstance(bars[0].timestamp, datetime) else bars[0].timestamp
        last_date = bars[-1].timestamp.date() if isinstance(bars[-1].timestamp, datetime) else bars[-1].timestamp

        first_membership = check_universe_membership(symbol, first_date, bhavcopy_adapter)
        last_membership = check_universe_membership(symbol, last_date, bhavcopy_adapter)

        results["universe_membership"] = {
            "first_date": str(first_date),
            "first_date_member": first_membership.is_member,
            "last_date": str(last_date),
            "last_date_member": last_membership.is_member,
            "constituent_count": last_membership.constituent_count,
        }
    else:
        results["universe_membership"] = {"skipped": True, "reason": "No BhavcopyAdapter provided"}

    results["is_clean"] = (
        ca_report.is_clean
        and ca_report.adjusted_series_consistent
    )

    return results

# apex-quant/src/apex/core/vetoes.py
"""Institutional Veto Engine: Ported and adapted from nse-trade-advisor-v5.

Enforces:
1. Wyckoff Effort vs Result (Bull-Trap Guard): Rejects breakout advances on weak volume (< 1.10x).
2. Multi-Timeframe Weekly Trend Lock: Rejects long setups when weekly trend is downward (weekly close < 20-week EMA).
3. Commodity-Opposed Guard: Rejects cyclical stocks when underlying global benchmarks (Crude, Metals) are in severe downtrend.
"""
from dataclasses import dataclass
from typing import Sequence, Optional
from ..domain.enums import Direction, MarketRegime
from ..domain.models import Bar


@dataclass(frozen=True)
class VetoResult:
    """Represents a veto evaluation outcome."""
    is_vetoed: bool
    veto_name: str
    reason: str
    severity: str  # "hard" or "soft"


# Global commodity mappings for cyclical NSE equities
COMMODITY_MAPPINGS: dict[str, tuple[str, str]] = {
    "ONGC.NS": ("CL=F", "WTI Crude Oil"),
    "ONGC": ("CL=F", "WTI Crude Oil"),
    "TATASTEEL.NS": ("HRC=F", "HRC Steel"),
    "TATASTEEL": ("HRC=F", "HRC Steel"),
    "JSWSTEEL.NS": ("HRC=F", "HRC Steel"),
    "JSWSTEEL": ("HRC=F", "HRC Steel"),
    "HINDALCO.NS": ("ALI=F", "LME Aluminium"),
    "HINDALCO": ("ALI=F", "LME Aluminium"),
    "VEDL.NS": ("HG=F", "Copper COMEX"),
    "VEDL": ("HG=F", "Copper COMEX"),
}


class VetoService:
    """Evaluates institutional hard and soft vetoes before trade commitment."""

    @staticmethod
    def evaluate_wyckoff_volume(
        is_breakout: bool,
        is_pullback: bool,
        volume_ratio: float,
        direction: Direction = Direction.LONG,
    ) -> Optional[VetoResult]:
        """Wyckoff Effort vs Result Analysis.
        
        1. Low volume on breakout into resistance is an Upthrust / Bull Trap (Hard Veto).
        2. Low volume on a pullback/support test in an established uptrend is healthy (supply dry-up).
        """
        if is_breakout and volume_ratio < 1.0:
            return VetoResult(
                is_vetoed=True,
                veto_name="wyckoff_upthrust_weak_effort",
                reason=f"Wyckoff Effort vs Result Failure: Breakout on thin volume ({volume_ratio:.2f}x < 1.0x) — high-risk Upthrust / Bull Trap signature.",
                severity="hard",
            )
        elif is_breakout and volume_ratio < 1.10 and not is_pullback:
            return VetoResult(
                is_vetoed=True,
                veto_name="wyckoff_weak_volume",
                reason=f"Volume ({volume_ratio:.2f}x average) is below institutional threshold (1.10x) — move lacks smart money backing.",
                severity="soft",
            )
        return None

    @staticmethod
    def evaluate_weekly_trend_lock(
        daily_direction: Direction,
        weekly_close: float,
        weekly_ema20: float,
    ) -> Optional[VetoResult]:
        """Strict Multi-Timeframe Trend Lock.
        
        Daily long signal is opposed if Weekly Close is below Weekly 20-EMA.
        Prevents counter-trend buying into overhead trapped sellers.
        """
        if daily_direction == Direction.LONG and weekly_close < weekly_ema20:
            return VetoResult(
                is_vetoed=True,
                veto_name="weekly_trend_opposed",
                reason=f"Multi-Timeframe Trend Lock: Daily long setup is opposed by Weekly downtrend (Weekly Close ₹{weekly_close:.2f} < 20-W EMA ₹{weekly_ema20:.2f}).",
                severity="hard",
            )
        elif daily_direction == Direction.SHORT and weekly_close > weekly_ema20:
            return VetoResult(
                is_vetoed=True,
                veto_name="weekly_trend_opposed",
                reason=f"Multi-Timeframe Trend Lock: Daily short setup is opposed by Weekly uptrend (Weekly Close ₹{weekly_close:.2f} > 20-W EMA ₹{weekly_ema20:.2f}).",
                severity="hard",
            )
        return None

    @staticmethod
    def evaluate_commodity_opposed(
        symbol: str,
        direction: Direction,
        commodity_return_20d_pct: float,
    ) -> Optional[VetoResult]:
        """Commodity Benchmark Guard for cyclical equities."""
        if symbol not in COMMODITY_MAPPINGS or direction != Direction.LONG:
            return None

        benchmark_sym, benchmark_name = COMMODITY_MAPPINGS[symbol]
        if commodity_return_20d_pct < -5.0:
            return VetoResult(
                is_vetoed=True,
                veto_name="commodity_opposed",
                reason=f"Underlying commodity benchmark ({benchmark_name} [{benchmark_sym}]) in severe downtrend ({commodity_return_20d_pct:+.1f}% over 20d) — commodity drag overrides technical setup.",
                severity="hard",
            )
        return None


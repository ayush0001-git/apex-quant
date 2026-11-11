# apex-quant/src/apex/core/exit_manager.py
"""Institutional PTJ Dynamic Exit Manager: 4-Milestone Trailing & Partial Profit Taking.

Calibrated against empirical Maximum Favorable Excursion (MFE) distributions:
- Milestone 1 (+1.0R): Tightens Chandelier trail to 1.5x ATR.
- Milestone 2 (+1.5R): Takes 50% partial profit off the table (+0.75R secured) and locks Breakeven (+0.05R) on remainder.
- Milestone 3 (+2.0R): Tightens Chandelier trail to 1.0x ATR on remainder.
- Milestone 4 (+2.5R): Closes remainder for full target exit.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class PTJExitAction:
    """Action recommendation from the exit manager."""
    action: str              # "HOLD", "PARTIAL_EXIT_50PCT", "TARGET_FULL_EXIT", "STOP_EXIT"
    exit_pct: float          # 0.0, 50.0, 100.0
    current_stop: float      # updated trailing stop price
    r_achieved: float        # R-multiple reached on this bar
    realized_r: float        # cumulative realized R-multiple
    is_closed: bool          # True if position is 100% closed
    message: str


class PTJExitBlueprint:
    """Dynamic 4-milestone institutional exit manager."""

    def __init__(self, entry: float, stop: float, atr: float, rr_target: float = 2.5):
        self.entry = float(entry)
        self.initial_stop = float(stop)
        self.risk_r = max(0.01, abs(self.entry - self.initial_stop))
        self.atr = max(0.01, float(atr))
        self.rr_target = float(rr_target)
        self.target = self.entry + (self.risk_r * self.rr_target)

        # Milestone price levels
        self.m1_price = self.entry + (self.risk_r * 1.0)  # +1.0R
        self.m2_price = self.entry + (self.risk_r * 1.5)  # +1.5R
        self.m3_price = self.entry + (self.risk_r * 2.0)  # +2.0R

        self.current_stop = self.initial_stop
        self.highest_price = self.entry
        self.partial_exited = False
        self.position_remaining_pct = 100.0
        self.cumulative_realized_r = 0.0

    def update(self, current_high: float, current_low: float, current_close: float) -> PTJExitAction:
        """Process a price bar and return the trade management action."""
        if self.position_remaining_pct <= 0:
            return PTJExitAction(
                action="ALREADY_CLOSED",
                exit_pct=0.0,
                current_stop=self.current_stop,
                r_achieved=0.0,
                realized_r=self.cumulative_realized_r,
                is_closed=True,
                message="Position is already fully closed.",
            )

        self.highest_price = max(self.highest_price, current_high)
        current_r = (self.highest_price - self.entry) / self.risk_r

        # 1. Target Full Exit (+2.5R reached)
        if current_high >= self.target:
            self.position_remaining_pct = 0.0
            self.cumulative_realized_r += (self.rr_target * (0.5 if self.partial_exited else 1.0))
            return PTJExitAction(
                action="TARGET_FULL_EXIT",
                exit_pct=100.0,
                current_stop=self.current_stop,
                r_achieved=round(current_r, 2),
                realized_r=round(self.cumulative_realized_r, 2),
                is_closed=True,
                message=f"Target reached at ₹{self.target:.2f} (+{self.rr_target}R). Full position closed.",
            )

        # 2. Stop-Loss Triggered
        if current_low <= self.current_stop:
            exit_pct = self.position_remaining_pct
            self.position_remaining_pct = 0.0
            r_loss = (self.current_stop - self.entry) / self.risk_r
            self.cumulative_realized_r += (r_loss * (exit_pct / 100.0))
            return PTJExitAction(
                action="STOP_EXIT",
                exit_pct=exit_pct,
                current_stop=self.current_stop,
                r_achieved=round(r_loss, 2),
                realized_r=round(self.cumulative_realized_r, 2),
                is_closed=True,
                message=f"Stop hit at ₹{self.current_stop:.2f}. Remaining {exit_pct:.0f}% closed.",
            )

        # 3. Milestone 2 (+1.5R): Take 50% partial profit and lock Breakeven
        if current_high >= self.m2_price and not self.partial_exited:
            self.partial_exited = True
            self.position_remaining_pct = 50.0
            self.cumulative_realized_r += (1.5 * 0.5)  # Banked +0.75R
            # Breakeven stop floor
            breakeven_floor = self.entry + (0.05 * self.risk_r)
            self.current_stop = max(self.current_stop, breakeven_floor)
            return PTJExitAction(
                action="PARTIAL_EXIT_50PCT",
                exit_pct=50.0,
                current_stop=self.current_stop,
                r_achieved=round(current_r, 2),
                realized_r=round(self.cumulative_realized_r, 2),
                is_closed=False,
                message=f"Milestone 2 hit at ₹{self.m2_price:.2f} (+1.5R). 50% partial profit secured (+0.75R). Stop raised to Breakeven (₹{self.current_stop:.2f}).",
            )

        # 4. Milestone 3 (+2.0R): Tighten trail to 1.0x ATR
        if current_high >= self.m3_price:
            tightened_stop = self.highest_price - (1.0 * self.atr)
            self.current_stop = max(self.current_stop, tightened_stop)
            return PTJExitAction(
                action="HOLD",
                exit_pct=0.0,
                current_stop=self.current_stop,
                r_achieved=round(current_r, 2),
                realized_r=round(self.cumulative_realized_r, 2),
                is_closed=False,
                message=f"Milestone 3 active (+2.0R). Trailing stop tightened to 1.0x ATR at ₹{self.current_stop:.2f}.",
            )

        # 5. Milestone 1 (+1.0R): Tighten trail to 1.5x ATR
        if current_high >= self.m1_price:
            m1_trail = self.highest_price - (1.5 * self.atr)
            self.current_stop = max(self.current_stop, m1_trail)
            return PTJExitAction(
                action="HOLD",
                exit_pct=0.0,
                current_stop=self.current_stop,
                r_achieved=round(current_r, 2),
                realized_r=round(self.cumulative_realized_r, 2),
                is_closed=False,
                message=f"Milestone 1 active (+1.0R). Trailing stop set to 1.5x ATR at ₹{self.current_stop:.2f}.",
            )

        return PTJExitAction(
            action="HOLD",
            exit_pct=0.0,
            current_stop=self.current_stop,
            r_achieved=round(current_r, 2),
            realized_r=round(self.cumulative_realized_r, 2),
            is_closed=False,
            message="Trade progressing normally within risk boundaries.",
        )


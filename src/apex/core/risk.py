# apex-quant/src/apex/core/risk.py
"""RiskGate: The uncompromising pure-math risk authority.

Strict single-ownership rules:
1. Zero LLM imports, zero prompt dependencies.
2. Zero BrokerPort references (cannot execute orders).
3. Evaluates TradeIntent against portfolio equity, daily drawdown, consecutive losses, and statutory friction.
4. Outputs RiskDecision (APPROVED or REJECTED with specific KillReason).
"""
from ..domain.models import TradeIntent, RiskDecision
from ..domain.enums import Direction, GateStatus, KillReason
from ..domain.config import Settings


class RiskGate:
    """Deterministic mathematical risk controller."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def evaluate(
        self,
        intent: TradeIntent,
        portfolio_equity: float,
        daily_pnl: float = 0.0,
        consecutive_losses: int = 0,
    ) -> RiskDecision:
        # 1. HOLD intent check
        if intent.direction == Direction.HOLD:
            return RiskDecision(
                status=GateStatus.REJECTED,
                reason="TradeIntent is HOLD",
                kill_reason=KillReason.NONE,
                position_size=None,
                max_capital_risk_pct=0.0,
                net_rr_ratio=0.0,
                estimated_statutory_friction=0.0,
            )

        # 2. Daily Drawdown Circuit Breaker
        # If loss exceeds max_daily_drawdown_pct (e.g. -2.0%)
        if portfolio_equity <= 0:
            return RiskDecision(
                status=GateStatus.REJECTED,
                reason="Portfolio equity is non-positive",
                kill_reason=KillReason.MAX_DAILY_DRAWDOWN,
                position_size=None,
                max_capital_risk_pct=0.0,
                net_rr_ratio=0.0,
                estimated_statutory_friction=0.0,
            )

        daily_loss_pct = abs(min(0.0, daily_pnl)) / portfolio_equity
        if daily_loss_pct >= self.settings.risk.max_daily_drawdown_pct:
            return RiskDecision(
                status=GateStatus.REJECTED,
                reason=f"Daily loss of {daily_loss_pct*100:.2f}% breached circuit breaker ({self.settings.risk.max_daily_drawdown_pct*100:.1f}%)",
                kill_reason=KillReason.MAX_DAILY_DRAWDOWN,
                position_size=None,
                max_capital_risk_pct=0.0,
                net_rr_ratio=0.0,
                estimated_statutory_friction=0.0,
            )

        # 3. Position Sizing (Fixed Fractional Risk)
        # Risk capital per trade = equity * max_position_pct (1.0%)
        risk_per_share = abs(intent.entry - intent.stop)
        if risk_per_share <= 0:
            return RiskDecision(
                status=GateStatus.REJECTED,
                reason="Invalid stop loss: risk per share is zero or negative",
                kill_reason=KillReason.NEGATIVE_NET_RR,
                position_size=None,
                max_capital_risk_pct=0.0,
                net_rr_ratio=0.0,
                estimated_statutory_friction=0.0,
            )

        max_risk_capital = portfolio_equity * self.settings.risk.max_position_pct

        # Throttle position size if consecutive losses >= threshold
        throttle_multiplier = 1.0
        if consecutive_losses >= self.settings.risk.consecutive_loss_throttle:
            throttle_multiplier = 0.5
            max_risk_capital *= throttle_multiplier

        target_quantity = int(max_risk_capital / risk_per_share)
        if target_quantity < 1:
            return RiskDecision(
                status=GateStatus.REJECTED,
                reason="Calculated position size is less than 1 share under risk limits",
                kill_reason=KillReason.NONE,
                position_size=None,
                max_capital_risk_pct=0.0,
                net_rr_ratio=0.0,
                estimated_statutory_friction=0.0,
            )

        # 4. Indian Statutory Friction & Slippage Modeling
        friction_cfg = self.settings.friction
        entry = intent.entry
        t1 = intent.targets[0] if intent.targets else entry
        turnover = (entry + t1) * target_quantity

        # Brokerage (₹20 entry + ₹20 exit = ₹40 flat)
        brokerage = friction_cfg.brokerage_per_order * 2.0
        # STT (0.02% on sell side for intraday)
        stt = t1 * target_quantity * friction_cfg.stt_intraday_pct
        # Exchange turnover (NSE 0.00325% on total turnover)
        exchange_charges = turnover * friction_cfg.exchange_turnover_pct
        # GST (18% on brokerage + exchange charges)
        gst = (brokerage + exchange_charges) * friction_cfg.gst_pct
        # Stamp Duty (0.003% on buy turnover)
        stamp_duty = (entry * target_quantity) * friction_cfg.stamp_duty_pct
        # Slippage (0.05% of turnover)
        slippage = turnover * friction_cfg.default_slippage_pct

        total_friction = brokerage + stt + exchange_charges + gst + stamp_duty + slippage

        # 5. Friction-Aware Net Expectancy Rule
        gross_profit = abs(t1 - entry) * target_quantity
        net_profit = gross_profit - total_friction

        # Must exceed 3.5x friction multiplier
        min_required_profit = total_friction * self.settings.risk.min_friction_multiplier
        if net_profit < min_required_profit:
            return RiskDecision(
                status=GateStatus.REJECTED,
                reason=f"Net profit (₹{net_profit:.2f}) is insufficient after friction (₹{total_friction:.2f}). Requires > {self.settings.risk.min_friction_multiplier}x friction.",
                kill_reason=KillReason.NEGATIVE_NET_RR,
                position_size=None,
                max_capital_risk_pct=round(self.settings.risk.max_position_pct * throttle_multiplier * 100, 2),
                net_rr_ratio=round(net_profit / (max_risk_capital + 1e-10), 2),
                estimated_statutory_friction=round(total_friction, 2),
            )

        net_rr = net_profit / max_risk_capital

        # 6. Approved!
        return RiskDecision(
            status=GateStatus.APPROVED,
            reason="All risk parameters, drawdown bounds, and friction hurdles passed.",
            kill_reason=KillReason.NONE,
            position_size=float(target_quantity),
            max_capital_risk_pct=round(self.settings.risk.max_position_pct * throttle_multiplier * 100, 2),
            net_rr_ratio=round(net_rr, 2),
            estimated_statutory_friction=round(total_friction, 2),
        )

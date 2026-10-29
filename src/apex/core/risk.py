# apex-quant/src/apex/core/risk.py
"""RiskGate: The uncompromising pure-math risk authority.

Strict single-ownership rules:
1. Zero LLM imports, zero prompt dependencies.
2. Zero BrokerPort references (cannot execute orders).
3. Evaluates TradeIntent against portfolio equity, daily drawdown, consecutive losses,
   and dynamic market impact & statutory friction.
4. Enforces defensive bounded throttling when qualitative debate signals divergence.
5. Evaluates portfolio-level Multi-Asset VaR, Expected Shortfall (CVaR), and Correlation Concentration.
6. Outputs RiskDecision (APPROVED or REJECTED with specific KillReason).
"""
from typing import Mapping, Sequence, Optional
from ..domain.models import TradeIntent, RiskDecision
from ..domain.enums import Direction, GateStatus, KillReason
from ..domain.config import Settings
from .slippage import DynamicSlippageModel
from .portfolio_risk import PortfolioRiskEngine, PortfolioRiskReport


class RiskGate:
    """Deterministic mathematical risk controller."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.slippage_model = DynamicSlippageModel(settings.friction)
        self.portfolio_risk_engine = PortfolioRiskEngine(
            max_portfolio_var_pct=settings.risk.max_portfolio_var_pct,
            max_portfolio_cvar_pct=settings.risk.max_portfolio_cvar_pct,
            max_asset_correlation=settings.risk.max_asset_correlation,
            max_sector_exposure_pct=settings.risk.max_sector_exposure_pct,
        )

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
            throttle_multiplier *= 0.5

        # Bounded Defensive Throttle from Qualitative LLM Debate:
        # If qualitative debate diverges or shows low conviction, scale down safely
        defensive_multiplier = 1.0
        if getattr(self.settings.risk, "llm_defensive_throttle", True) and intent.debate:
            conf = getattr(intent.debate, "confidence_score", 0.0)
            if intent.direction == Direction.LONG and conf < -0.1:
                defensive_multiplier = max(0.5, min(1.0, 0.7 + 0.3 * (conf + 1.0) / 2.0))
            elif intent.direction == Direction.SHORT and conf > 0.1:
                defensive_multiplier = max(0.5, min(1.0, 0.7 + 0.3 * (1.0 - conf) / 2.0))

        throttle_multiplier *= defensive_multiplier

        # Volatility Gate: dampens position size during elevated turbulence
        vol_gate = getattr(intent.feature_snapshot, "volatility_gate", 1.0) if intent.feature_snapshot else 1.0
        throttle_multiplier *= vol_gate

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
                defensive_multiplier=round(defensive_multiplier, 2),
            )

        # 4. Indian Statutory Friction & Dynamic Slippage Modeling
        friction_cfg = self.settings.friction
        entry = intent.entry
        t1 = intent.targets[0] if intent.targets else entry
        turnover = (entry + t1) * target_quantity

        # Brokerage (flat ₹20 entry + ₹20 exit = ₹40 flat)
        brokerage = friction_cfg.brokerage_per_order * 2.0
        # STT (0.02% on sell side for intraday)
        stt = t1 * target_quantity * friction_cfg.stt_intraday_pct
        # Exchange turnover (NSE 0.00325% on total turnover)
        exchange_charges = turnover * friction_cfg.exchange_turnover_pct
        # GST (18% on brokerage + exchange charges)
        gst = (brokerage + exchange_charges) * friction_cfg.gst_pct
        # Stamp Duty (0.003% on buy turnover)
        stamp_duty = (entry * target_quantity) * friction_cfg.stamp_duty_pct

        # Dynamic Slippage Calculation:
        # Accounts for current bar volume ratio, realized volatility, and order turnover impact
        vol_ratio = getattr(intent.feature_snapshot, "volume_ratio", 1.0) if intent.feature_snapshot else 1.0
        atr = intent.feature_snapshot.indicators.get("atr_14", entry * 0.015) if intent.feature_snapshot else entry * 0.015
        vol_pct = atr / (entry + 1e-8)

        slippage_quote = self.slippage_model.estimate_slippage(
            turnover=turnover,
            shares=target_quantity,
            spot_price=entry,
            volume_ratio=vol_ratio,
            volatility_pct=vol_pct,
        )
        slippage = slippage_quote.slippage_inr

        total_friction = brokerage + stt + exchange_charges + gst + stamp_duty + slippage

        # 5. Friction-Aware Net Expectancy Rule
        gross_profit = abs(t1 - entry) * target_quantity
        net_profit = gross_profit - total_friction

        # Must exceed minimum friction multiplier hurdle (default 3.5x)
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
                dynamic_slippage_bps=slippage_quote.slippage_bps,
                defensive_multiplier=round(defensive_multiplier, 2),
            )

        net_rr = net_profit / max_risk_capital

        # 6. Approved!
        return RiskDecision(
            status=GateStatus.APPROVED,
            reason="All risk parameters, drawdown bounds, dynamic slippage, and friction hurdles passed.",
            kill_reason=KillReason.NONE,
            position_size=float(target_quantity),
            max_capital_risk_pct=round(self.settings.risk.max_position_pct * throttle_multiplier * 100, 2),
            net_rr_ratio=round(net_rr, 2),
            estimated_statutory_friction=round(total_friction, 2),
            dynamic_slippage_bps=slippage_quote.slippage_bps,
            defensive_multiplier=round(defensive_multiplier, 2),
        )

    def evaluate_portfolio(
        self,
        positions: Mapping[str, float],
        historical_returns: Mapping[str, Sequence[float]],
        total_equity: float,
    ) -> PortfolioRiskReport:
        """Run multi-asset Portfolio VaR, Expected Shortfall, and Stress Testing."""
        return self.portfolio_risk_engine.evaluate_portfolio(
            positions=positions,
            historical_returns=historical_returns,
            total_equity=total_equity,
        )

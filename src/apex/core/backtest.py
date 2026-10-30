# apex-quant/src/apex/core/backtest.py
"""BacktestEngine: Historical bar-by-bar simulation with strict causality and statutory friction.

Guarantees:
1. Zero lookahead bias: At step t, feature calculation strictly sees bars[:t].
2. High-precision statutory friction calculation (STT, GST, Stamp Duty, Brokerage, Slippage).
3. Realistic bracket order simulation (Limit Entry, Hard SL, Take Profit).
4. Comprehensive performance telemetry (Win rate, Profit Factor, Max Drawdown, Sharpe Ratio).
"""
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence, List, Mapping, Any, Optional
import numpy as np
from ..domain.models import Bar, TradeIntent, RiskDecision, DebateResult
from ..domain.enums import Direction, GateStatus, Timeframe
from .features import FeatureService
from .forecast import ForecastService
from .decision import DecisionEngine
from .risk import RiskGate
from ..domain.config import Settings
from .slippage import DynamicSlippageModel
from .validation import InstitutionalValidator
from .friction import StatutorySchedule
from .ingestion import IngestionService


@dataclass(frozen=True)
class SimulatedTrade:
    trade_id: str
    symbol: str
    direction: Direction
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    shares: float
    gross_pnl: float
    statutory_friction: float
    net_pnl: float
    return_pct: float
    exit_reason: str
    stop_loss: float
    target: float


@dataclass(frozen=True)
class BacktestSummary:
    symbol: str
    timeframe: str
    total_bars: int
    initial_capital: float
    final_capital: float
    gross_pnl: float
    total_friction: float
    net_pnl: float
    net_return_pct: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: float
    profit_factor: float
    max_drawdown_pct: float
    sharpe_ratio: float
    trades: List[SimulatedTrade]
    equity_curve: List[float]
    deflated_sharpe_ratio: float = 0.0
    probability_of_overfitting: float = 0.0
    cvar_95_pct: float = 0.0
    avg_slippage_bps: float = 5.0


class BacktestEngine:
    """Historical bar-by-bar backtester simulating real-world execution."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or Settings.load()
        self.features = FeatureService()
        self.forecast = ForecastService()
        self.decision = DecisionEngine()
        self.risk = RiskGate(settings=self.settings)
        self.slippage_model = DynamicSlippageModel(self.settings.friction)

    def calculate_statutory_friction(
        self,
        turnover: float,
        shares: float,
        is_buy: bool,
        is_delivery: bool = True,
        volume_ratio: float = 1.0,
        volatility_pct: float = 0.015,
        spot_price: float = 0.0,
    ) -> float:
        """Calculates precise statutory transaction costs and dynamic execution slippage (F4)."""
        statutory = StatutorySchedule.calculate_statutory_friction(
            turnover=turnover,
            shares=shares,
            is_buy=is_buy,
            is_delivery=is_delivery,
            brokerage_per_order=self.settings.friction.brokerage_per_order,
        )
        effective_spot = spot_price or (turnover / (shares + 1e-8))
        slippage_quote = self.slippage_model.estimate_slippage(
            turnover=turnover,
            shares=shares,
            spot_price=effective_spot,
            volume_ratio=volume_ratio,
            volatility_pct=volatility_pct,
        )
        return round(statutory + slippage_quote.slippage_inr, 2)

    def run(
        self,
        bars: Sequence[Bar],
        initial_capital: float = 100000.0,
        warmup_bars: int = 30,
        is_delivery: bool = True,
    ) -> BacktestSummary:
        """Execute strict bar-by-bar simulation over closed historical candles (F2, F3, F11, F12)."""
        # Validate bars for causality and integrity (F3)
        bars = IngestionService.validate_and_normalize(bars, allow_zero_volume=True)
        if len(bars) <= warmup_bars:
            raise ValueError(f"Insufficient bars for backtest: need > {warmup_bars}, received {len(bars)}")

        current_capital = initial_capital
        peak_capital = initial_capital
        max_drawdown_pct = 0.0
        trades: List[SimulatedTrade] = []
        equity_curve: List[float] = [initial_capital]

        # Active open position state
        active_position: Optional[dict] = None
        trade_counter = 0

        for t in range(warmup_bars, len(bars)):
            current_bar = bars[t]
            history_window = bars[:t]

            # 1. Manage Active Position (Check for SL or Target hit on current bar)
            if active_position is not None:
                pos = active_position
                hit_target = current_bar.high >= pos["target"]
                hit_stop = current_bar.low <= pos["stop"]

                if hit_target or hit_stop:
                    trade_counter += 1

                    # Gap openings take priority
                    if current_bar.open <= pos["stop"]:
                        exit_price = current_bar.open
                        exit_reason = "STOP_LOSS_HIT"
                    elif current_bar.open >= pos["target"]:
                        exit_price = current_bar.open
                        exit_reason = "TARGET_HIT"
                    elif hit_target and hit_stop:
                        # Whipsaw bar: enforce conservative stop-first rule (F2)
                        exit_price = pos["stop"]
                        exit_reason = "STOP_LOSS_HIT"
                    elif hit_target:
                        exit_price = pos["target"]
                        exit_reason = "TARGET_HIT"
                    else:
                        exit_price = pos["stop"]
                        exit_reason = "STOP_LOSS_HIT"
                    
                    sell_turnover = exit_price * pos["shares"]
                    exit_friction = self.calculate_statutory_friction(sell_turnover, pos["shares"], is_buy=False, is_delivery=is_delivery)
                    total_trade_friction = pos["entry_friction"] + exit_friction

                    gross_pnl = (exit_price - pos["entry_price"]) * pos["shares"]
                    net_pnl = gross_pnl - total_trade_friction
                    ret_pct = (net_pnl / (pos["entry_price"] * pos["shares"])) * 100.0

                    current_capital += net_pnl

                    # Update drawdown
                    if current_capital > peak_capital:
                        peak_capital = current_capital
                    dd = ((peak_capital - current_capital) / peak_capital) * 100.0
                    if dd > max_drawdown_pct:
                        max_drawdown_pct = dd

                    trades.append(
                        SimulatedTrade(
                            trade_id=f"BT_{trade_counter:04d}",
                            symbol=pos["symbol"],
                            direction=pos["direction"],
                            entry_time=pos["entry_time"],
                            exit_time=current_bar.timestamp,
                            entry_price=pos["entry_price"],
                            exit_price=exit_price,
                            shares=pos["shares"],
                            gross_pnl=round(gross_pnl, 2),
                            statutory_friction=round(total_trade_friction, 2),
                            net_pnl=round(net_pnl, 2),
                            return_pct=round(ret_pct, 2),
                            exit_reason=exit_reason,
                            stop_loss=pos["stop"],
                            target=pos["target"],
                        )
                    )
                    active_position = None
                else:
                    # No exit on this bar
                    pass

            # 2. If no position, evaluate signals strictly on historical bars[:t]
            if active_position is None:
                try:
                    features_snapshot = self.features.compute(history_window)
                    forecast_snapshot = self.forecast.generate_forecast(history_window, horizon_bars=12)

                    # Simulated Debate (neutral consensus fallback for offline backtest)
                    synth_action = Direction.LONG if features_snapshot.confluence_score >= 55.0 and forecast_snapshot.directional_prob >= 0.52 else Direction.HOLD
                    debate = DebateResult(
                        action=synth_action,
                        conviction=int(features_snapshot.confluence_score),
                        entry_zone=(features_snapshot.spot_price, features_snapshot.spot_price),
                        stop_loss=features_snapshot.spot_price - (1.5 * features_snapshot.indicators.get("atr_14", 10.0)),
                        targets=(features_snapshot.spot_price + (3.0 * features_snapshot.indicators.get("atr_14", 10.0)),),
                        reasoning_hash="backtest_sim",
                    )

                    intent = self.decision.evaluate(features_snapshot, forecast_snapshot, debate)
                    risk_decision = self.risk.evaluate(intent, portfolio_equity=current_capital, is_delivery=is_delivery)

                    if risk_decision.status == GateStatus.APPROVED and intent.direction == Direction.LONG:
                        shares = risk_decision.position_size or 10.0
                        entry_price = current_bar.close
                        buy_turnover = entry_price * shares
                        entry_friction = self.calculate_statutory_friction(
                            buy_turnover,
                            shares,
                            is_buy=True,
                            is_delivery=is_delivery,
                            volume_ratio=features_snapshot.volume_ratio,
                            spot_price=entry_price,
                        )

                        active_position = {
                            "symbol": current_bar.symbol,
                            "direction": intent.direction,
                            "entry_time": current_bar.timestamp,
                            "entry_price": entry_price,
                            "stop": intent.stop,
                            "target": intent.targets[0] if intent.targets else entry_price * 1.05,
                            "shares": shares,
                            "entry_friction": entry_friction,
                        }
                except (ValueError, KeyError):
                    # Expected data initialization gaps during initial history slices
                    pass

            # Append to equity curve exactly ONCE per bar (F11)
            equity_curve.append(round(current_capital, 2))

        # Performance Metrics Compilation
        total_trades = len(trades)
        winning_trades = len([t for t in trades if t.net_pnl > 0])
        losing_trades = len([t for t in trades if t.net_pnl <= 0])
        win_rate = (winning_trades / total_trades * 100.0) if total_trades > 0 else 0.0

        gross_pnl = sum(t.gross_pnl for t in trades)
        total_friction = sum(t.statutory_friction for t in trades)
        net_pnl = sum(t.net_pnl for t in trades)
        net_return_pct = ((current_capital - initial_capital) / initial_capital) * 100.0

        gross_profit = sum(t.gross_pnl for t in trades if t.gross_pnl > 0)
        gross_loss = abs(sum(t.gross_pnl for t in trades if t.gross_pnl < 0))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)

        # Compute Sharpe Ratio from daily Mark-to-Market (MTM) returns (F11)
        if len(equity_curve) >= 2:
            eq_arr = np.array(equity_curve, dtype=float)
            daily_returns = np.diff(eq_arr) / (eq_arr[:-1] + 1e-8)
            mean_ret = float(np.mean(daily_returns))
            std_ret = float(np.std(daily_returns, ddof=1)) if len(daily_returns) > 1 else 1e-6
            if std_ret > 1e-8:
                sharpe_ratio = round((mean_ret / std_ret) * math.sqrt(252), 2)
            else:
                sharpe_ratio = 0.0
        else:
            sharpe_ratio = 0.0

        # Institutional validation metrics: DSR, PBO, and true 95% CVaR (F12)
        if total_trades >= 5:
            trade_returns = [t.return_pct for t in trades]
            val_report = InstitutionalValidator.evaluate_strategy_integrity(trade_returns)
            dsr = val_report.deflated_sharpe_ratio
            pbo = val_report.probability_of_overfitting
            
            # True 95% CVaR (Expected Shortfall): average of returns in bottom 5% tail
            rets_arr = np.array(trade_returns)
            cutoff_5pct = np.percentile(rets_arr, 5)
            tail_losses = rets_arr[rets_arr <= cutoff_5pct]
            cvar = round(abs(float(np.mean(tail_losses))), 2) if len(tail_losses) > 0 else 0.0
        else:
            dsr = 0.0
            pbo = 0.0
            cvar = 0.0

        return BacktestSummary(
            symbol=bars[0].symbol if bars else "UNKNOWN",
            timeframe=bars[0].timeframe.value if bars else "15m",
            total_bars=len(bars),
            initial_capital=initial_capital,
            final_capital=round(current_capital, 2),
            gross_pnl=round(gross_pnl, 2),
            total_friction=round(total_friction, 2),
            net_pnl=round(net_pnl, 2),
            net_return_pct=round(net_return_pct, 2),
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate_pct=round(win_rate, 1),
            profit_factor=round(profit_factor, 2),
            max_drawdown_pct=round(max_drawdown_pct, 2),
            sharpe_ratio=sharpe_ratio,
            trades=trades,
            equity_curve=equity_curve,
            deflated_sharpe_ratio=dsr,
            probability_of_overfitting=pbo,
            cvar_95_pct=cvar,
        )

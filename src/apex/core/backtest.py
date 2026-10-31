# apex-quant/src/apex/core/backtest.py
"""BacktestEngine: Historical bar-by-bar simulation with strict causality and statutory friction.

Guarantees:
1. Zero lookahead bias: At step t, feature calculation strictly sees bars[:t].
2. High-precision statutory friction calculation (STT, GST, Stamp Duty, Brokerage, Slippage).
3. Realistic bracket order simulation (Limit Entry, Hard SL, Take Profit).
4. Comprehensive performance telemetry (Win rate, Profit Factor, Max Drawdown, Sharpe Ratio).
"""
import logging
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence, List, Mapping, Any, Optional
import numpy as np
from ..domain.models import Bar, TradeIntent, RiskDecision, DebateResult
from ..domain.enums import Direction, GateStatus, Timeframe, MarketRegime
from .features import FeatureService
from .forecast import ForecastService
from .decision import DecisionEngine
from .risk import RiskGate
from ..domain.config import Settings
from .slippage import DynamicSlippageModel
from .validation import InstitutionalValidator
from .friction import StatutorySchedule
from .ingestion import IngestionService
from .regime import GaussianHMMRegimeDetector
from ..adapters.data.fundamental_adapter import FundamentalAdapter

logger = logging.getLogger(__name__)


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
    sortino_ratio: float = 0.0
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
        self.fundamental = FundamentalAdapter()

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
        """Execute strict bar-by-bar simulation over closed historical candles with MTM accounting (P0-2)."""
        # Clear HMM cache between backtest runs to avoid state leakage (P1-8)
        GaussianHMMRegimeDetector.clear_cache()

        # Validate bars for causality and integrity (F3)
        bars = IngestionService.validate_and_normalize(bars, allow_zero_volume=True)
        if len(bars) <= warmup_bars:
            raise ValueError(f"Insufficient bars for backtest: need > {warmup_bars}, received {len(bars)}")

        cash = initial_capital
        current_capital = initial_capital
        peak_capital = initial_capital
        max_drawdown_pct = 0.0
        trades: List[SimulatedTrade] = []
        equity_curve: List[float] = [initial_capital]

        # Active open position state & cooldown tracker
        active_position: Optional[dict] = None
        trade_counter = 0
        last_exit_step: int = -999

        for t in range(warmup_bars, len(bars)):
            current_bar = bars[t]
            history_window = bars[:t]

            # 1. Manage Active Position (Trailing Stop + Target/Stop Exit)
            if active_position is not None:
                pos = active_position
                atr_val = pos.get("atr", 10.0)

                # Friction-Aware Swing Trailing Stop:
                # Once favorable move >= 1.9 * ATR, lock in +0.40 * ATR (covers all friction and secures win)
                favorable_move = current_bar.high - pos["entry_price"]
                if favorable_move >= 1.9 * atr_val:
                    pos["stop"] = max(pos["stop"], pos["entry_price"] + (0.40 * atr_val))
                if favorable_move >= 2.7 * atr_val:
                    pos["stop"] = max(pos["stop"], pos["entry_price"] + (1.20 * atr_val))

                hit_target = current_bar.high >= pos["target"]
                hit_stop = current_bar.low <= pos["stop"]

                if hit_target or hit_stop:
                    trade_counter += 1
                    last_exit_step = t

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
                    exit_friction = self.calculate_statutory_friction(
                        sell_turnover,
                        pos["shares"],
                        is_buy=False,
                        is_delivery=is_delivery,
                        volume_ratio=1.0,
                        spot_price=exit_price,
                    )
                    total_trade_friction = pos["entry_friction"] + exit_friction

                    gross_pnl = (exit_price - pos["entry_price"]) * pos["shares"]
                    net_pnl = gross_pnl - total_trade_friction
                    ret_pct = (net_pnl / (pos["entry_price"] * pos["shares"])) * 100.0

                    cash += (sell_turnover - exit_friction)
                    current_capital = cash

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

            # 2. If no position, evaluate signals strictly on historical bars[:t]
            # Enforce 4-bar cooldown after exit to prevent churning
            if active_position is None and (t - last_exit_step >= 4):
                try:
                    features_snapshot = self.features.compute(history_window)
                    forecast_snapshot = self.forecast.generate_forecast(history_window, horizon_bars=12)

                    ema_20 = features_snapshot.indicators.get("ema_20", 0.0)
                    ema_50 = features_snapshot.indicators.get("ema_50", 0.0)
                    mom_20 = features_snapshot.indicators.get("momentum_20", 0.0)
                    vol_gate = getattr(features_snapshot, "volatility_gate", 1.0)
                    rsi = features_snapshot.indicators.get("rsi_14", 50.0)

                    # Institutional Regime & Quality Filters:
                    # 1. Reject range compression, bear expansion, and turbulence
                    regime_ok = features_snapshot.regime not in [
                        MarketRegime.RANGE_COMPRESSION,
                        MarketRegime.BEAR_EXPANSION,
                        MarketRegime.HIGH_VOLATILITY_TURBULENCE,
                    ]
                    # 2. Positive 20-day momentum
                    mom_ok = mom_20 >= 0.20
                    # 3. Bullish trend alignment (Spot >= EMA50 and EMA20 >= EMA50)
                    trend_ok = (features_snapshot.spot_price >= ema_50 and ema_20 >= ema_50) if (ema_50 > 0 and ema_20 > 0) else True
                    # 4. RSI sanity bounds (avoids buying extreme overbought or dead momentum)
                    rsi_ok = (42.0 <= rsi <= 72.0)
                    # 5. Confluence & predictive forecast probability
                    conviction_ok = (
                        features_snapshot.confluence_score >= 56.0 and
                        forecast_snapshot.directional_prob >= 0.50 and
                        vol_gate >= 0.50
                    )

                    atr_val = features_snapshot.indicators.get("atr_14", current_bar.close * 0.015)

                    # 6. Fundamental Quality Gate
                    fund = self.fundamental.get_fundamentals(current_bar.symbol)
                    fund_ok = (fund.piotroski_score >= 6) and (fund.debt_to_equity <= 1.2 or fund.roe_pct >= 14.0)

                    # 7. Pullback to Value Filter: prevent overextended chase entries (>1.15 * ATR above EMA20)
                    dist_from_ema20 = (features_snapshot.spot_price - ema_20) / atr_val if (ema_20 > 0 and atr_val > 0) else 0.0
                    pullback_ok = dist_from_ema20 <= 1.15

                    is_high_conviction = regime_ok and mom_ok and trend_ok and rsi_ok and conviction_ok and fund_ok and pullback_ok
                    synth_action = Direction.LONG if is_high_conviction else Direction.HOLD

                    # Stop: 1.8 * ATR, Target: 3.2 * ATR (Positive 1:1.78 Risk-Reward)
                    debate = DebateResult(
                        action=synth_action,
                        conviction=int(features_snapshot.confluence_score),
                        entry_zone=(features_snapshot.spot_price, features_snapshot.spot_price),
                        stop_loss=features_snapshot.spot_price - (1.8 * atr_val),
                        targets=(features_snapshot.spot_price + (3.2 * atr_val),),
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

                        cash -= (buy_turnover + entry_friction)

                        active_position = {
                            "symbol": current_bar.symbol,
                            "direction": intent.direction,
                            "entry_time": current_bar.timestamp,
                            "entry_price": entry_price,
                            "stop": intent.stop,
                            "target": intent.targets[0] if intent.targets else entry_price * 1.05,
                            "shares": shares,
                            "entry_friction": entry_friction,
                            "atr": atr_val,
                        }
                except (ValueError, KeyError):
                    pass

            # 3. Mark-to-Market (MTM) Portfolio Equity Calculation (P0-2)
            if active_position is not None:
                unrealized_position_value = active_position["shares"] * current_bar.close
                bar_equity = cash + unrealized_position_value
            else:
                bar_equity = cash

            current_capital = bar_equity

            # Update peak equity and intratrade drawdown
            if bar_equity > peak_capital:
                peak_capital = bar_equity
            dd = ((peak_capital - bar_equity) / peak_capital) * 100.0
            if dd > max_drawdown_pct:
                max_drawdown_pct = dd

            equity_curve.append(round(bar_equity, 2))

        # Close any lingering open position at final bar close for full audit resolution
        if active_position is not None:
            last_bar = bars[-1]
            trade_counter += 1
            exit_price = last_bar.close
            exit_reason = "END_OF_DATA_CLOSE"
            sell_turnover = exit_price * active_position["shares"]
            exit_friction = self.calculate_statutory_friction(
                sell_turnover, active_position["shares"], is_buy=False, is_delivery=is_delivery
            )
            total_trade_friction = active_position["entry_friction"] + exit_friction
            gross_pnl = (exit_price - active_position["entry_price"]) * active_position["shares"]
            net_pnl = gross_pnl - total_trade_friction
            ret_pct = (net_pnl / (active_position["entry_price"] * active_position["shares"])) * 100.0

            cash += (sell_turnover - exit_friction)
            current_capital = cash

            trades.append(
                SimulatedTrade(
                    trade_id=f"BT_{trade_counter:04d}",
                    symbol=active_position["symbol"],
                    direction=active_position["direction"],
                    entry_time=active_position["entry_time"],
                    exit_time=last_bar.timestamp,
                    entry_price=active_position["entry_price"],
                    exit_price=exit_price,
                    shares=active_position["shares"],
                    gross_pnl=round(gross_pnl, 2),
                    statutory_friction=round(total_trade_friction, 2),
                    net_pnl=round(net_pnl, 2),
                    return_pct=round(ret_pct, 2),
                    exit_reason=exit_reason,
                    stop_loss=active_position["stop"],
                    target=active_position["target"],
                )
            )
            active_position = None

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

        # Compute Sharpe & Sortino Ratio from daily Mark-to-Market (MTM) returns (P0-2)
        sortino_ratio = 0.0
        if len(equity_curve) >= 2:
            eq_arr = np.array(equity_curve, dtype=float)
            daily_returns = np.diff(eq_arr) / (eq_arr[:-1] + 1e-8)
            mean_ret = float(np.mean(daily_returns))
            std_ret = float(np.std(daily_returns, ddof=1)) if len(daily_returns) > 1 else 1e-6
            if std_ret > 1e-8:
                sharpe_ratio = round((mean_ret / std_ret) * math.sqrt(252), 2)
            else:
                sharpe_ratio = 0.0

            downside_rets = daily_returns[daily_returns < 0.0]
            if len(downside_rets) > 1:
                downside_std = float(np.std(downside_rets, ddof=1))
                sortino_ratio = round((mean_ret / (downside_std + 1e-8)) * math.sqrt(252), 2)
            else:
                sortino_ratio = max(0.0, sharpe_ratio)

            if sharpe_ratio > 3.0:
                logger.warning("Backtest Sharpe %.2f > 3.0 indicates structurally optimistic assumptions", sharpe_ratio)
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
            sortino_ratio=sortino_ratio,
            trades=trades,
            equity_curve=equity_curve,
            deflated_sharpe_ratio=dsr,
            probability_of_overfitting=pbo,
            cvar_95_pct=cvar,
        )

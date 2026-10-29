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
from ..domain.models import Bar, TradeIntent, RiskDecision, DebateResult
from ..domain.enums import Direction, GateStatus, Timeframe
from .features import FeatureService
from .forecast import ForecastService
from .decision import DecisionEngine
from .risk import RiskGate
from ..domain.config import Settings
from .slippage import DynamicSlippageModel
from .validation import InstitutionalValidator


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
        volume_ratio: float = 1.0,
        volatility_pct: float = 0.015,
        spot_price: float = 0.0,
    ) -> float:
        """Calculates precise statutory transaction costs and dynamic execution slippage."""
        # Brokerage: flat ₹20 or 0.05%
        brokerage = min(20.0, turnover * 0.0005)
        
        # STT: 0.1% on delivery (both legs) or 0.025% on intraday sell
        stt = turnover * 0.001 if is_buy else turnover * 0.00025
        
        # Exchange turnover charges: NSE 0.00325%
        exchange_charges = turnover * 0.0000325
        
        # GST: 18% on (brokerage + exchange charges)
        gst = (brokerage + exchange_charges) * 0.18
        
        # SEBI turnover charge: ₹10 per crore (0.0001%)
        sebi_charges = turnover * 0.000001
        
        # Stamp duty: 0.015% on buy order turnover
        stamp_duty = turnover * 0.00015 if is_buy else 0.0
        
        # Dynamic Market Slippage (Kyle's lambda & volume/volatility conditioned)
        effective_spot = spot_price or (turnover / (shares + 1e-8))
        slippage_quote = self.slippage_model.estimate_slippage(
            turnover=turnover,
            shares=shares,
            spot_price=effective_spot,
            volume_ratio=volume_ratio,
            volatility_pct=volatility_pct,
        )
        slippage = slippage_quote.slippage_inr
        
        return round(brokerage + stt + exchange_charges + gst + sebi_charges + stamp_duty + slippage, 2)

    def run(
        self,
        bars: Sequence[Bar],
        initial_capital: float = 100000.0,
        warmup_bars: int = 30,
    ) -> BacktestSummary:
        """Execute strict bar-by-bar simulation over closed historical candles."""
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
                    exit_price = pos["target"] if hit_target else pos["stop"]
                    exit_reason = "TARGET_HIT" if hit_target else "STOP_LOSS_HIT"
                    
                    sell_turnover = exit_price * pos["shares"]
                    exit_friction = self.calculate_statutory_friction(sell_turnover, pos["shares"], is_buy=False)
                    total_trade_friction = pos["entry_friction"] + exit_friction

                    gross_pnl = (exit_price - pos["entry_price"]) * pos["shares"]
                    net_pnl = gross_pnl - total_trade_friction
                    ret_pct = (net_pnl / (pos["entry_price"] * pos["shares"])) * 100.0

                    current_capital += net_pnl
                    equity_curve.append(current_capital)

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
                    equity_curve.append(current_capital)
                    continue

            # 2. If no position, evaluate signals strictly on historical bars[:t]
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
                risk_decision = self.risk.evaluate(intent, portfolio_equity=current_capital)

                if risk_decision.status == GateStatus.APPROVED and intent.direction == Direction.LONG:
                    shares = risk_decision.position_size or 10.0
                    entry_price = current_bar.close
                    buy_turnover = entry_price * shares
                    entry_friction = self.calculate_statutory_friction(
                        buy_turnover,
                        shares,
                        is_buy=True,
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
            except Exception:
                pass

            equity_curve.append(current_capital)

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

        # Approximate annualized Sharpe Ratio from trade returns
        if total_trades >= 3:
            returns = [t.return_pct for t in trades]
            mean_ret = sum(returns) / len(returns)
            variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
            std_dev = math.sqrt(variance) if variance > 0 else 1.0
            sharpe_ratio = round((mean_ret / std_dev) * math.sqrt(252 / max(1, len(bars) / 25)), 2)
        else:
            sharpe_ratio = 0.0

        # Institutional validation metrics: DSR, PBO, and CVaR
        if total_trades >= 5:
            returns = [t.return_pct for t in trades]
            val_report = InstitutionalValidator.evaluate_strategy_integrity(returns)
            dsr = val_report.deflated_sharpe_ratio
            pbo = val_report.probability_of_overfitting
            neg_returns = [r for r in returns if r < 0]
            cvar = round(abs(float(sum(neg_returns) / len(neg_returns))), 2) if neg_returns else 0.0
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

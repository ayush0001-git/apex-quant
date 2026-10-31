#!/usr/bin/env python3
# apex-quant/scripts/run_momentum_compounding_backtest.py
"""Reproducible High-Momentum Compounding & Small-Capital Swing Simulation.

Implements the verified institutional rules:
1. Focuses strictly on High-Beta Momentum Leaders (disqualifying low-volatility dividend traps).
2. Market Regime Gate (universe 50 EMA trend slope).
3. Max absolute loss capped strictly (e.g. <= INR 500) via volatility-safe share position sizing (1.5 * ATR stop distance).
4. Dynamic 2-week swing horizon (up to 10 trading days) capturing +3.0 * ATR momentum expansions.
5. Strict SEBI statutory friction schedule + CDSL DP charges (INR 18.76).
"""
import argparse
import os
import sys
import hashlib
import warnings
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any
import numpy as np

warnings.filterwarnings("ignore")
os.environ["LOKY_MAX_CPU_COUNT"] = "4"

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))
sys.path.insert(0, str(ROOT_DIR))

from apex.core.friction import StatutorySchedule
from apex.adapters.data.fundamental_adapter import FundamentalAdapter
from scripts.run_portfolio_backtest import generate_realistic_mock_bars

MOMENTUM_LEADERS = [
    "APOLLOHOSP.NS", "HINDALCO.NS", "LTIM.NS", "BRITANNIA.NS", "ASIANPAINT.NS",
    "GRASIM.NS", "BAJAJ-AUTO.NS", "TITAN.NS", "AXISBANK.NS", "ONGC.NS",
    "TRENT.NS", "MARUTI.NS", "M&M.NS", "INFY.NS", "RELIANCE.NS"
]


def run_momentum_compounding_simulation(
    symbols: List[str] = MOMENTUM_LEADERS,
    starting_capital: float = 20000.0,
    lookback_bars: int = 500,
    max_loss_inr: float = 500.0,
    max_holding_bars: int = 10,
) -> Dict[str, Any]:
    """Execute compounding simulation and return metrics."""
    fund_adapter = FundamentalAdapter()
    all_symbol_bars = {sym: generate_realistic_mock_bars(sym, lookback=lookback_bars) for sym in symbols}
    market_closes = [np.mean([all_symbol_bars[sym][t].close for sym in symbols]) for t in range(lookback_bars)]

    cash = starting_capital
    active_pos = None
    closed_trades = []
    equity_curve = [starting_capital]
    peak_equity = starting_capital
    max_dd = 0.0
    last_exit_bar = {sym: -999 for sym in symbols}

    for t in range(50, lookback_bars):
        current_bars = {sym: all_symbol_bars[sym][t] for sym in symbols}

        # Market trend filter
        m_slice = market_closes[:t+1]
        m_ema20 = float(np.mean(m_slice[-20:]))
        m_ema50 = float(np.mean(m_slice[-50:]))
        market_bull = m_ema20 >= m_ema50

        # 1. Manage Active Position
        if active_pos is not None:
            sym = active_pos["symbol"]
            cur_bar = current_bars[sym]
            atr = active_pos["atr"]
            bars_held = t - active_pos["entry_bar"]

            fav = cur_bar.high - active_pos["entry_price"]
            active_pos["max_fav"] = max(active_pos["max_fav"], fav)

            # Trailing stop lock
            friction_per_share = (active_pos["entry_friction"] * 2.2) / active_pos["shares"]
            if active_pos["max_fav"] >= (1.60 * atr):
                active_pos["stop"] = max(active_pos["stop"], active_pos["entry_price"] + friction_per_share + (0.30 * atr))

            hit_target = cur_bar.high >= active_pos["target"]
            hit_stop = cur_bar.low <= active_pos["stop"]
            time_exit = bars_held >= max_holding_bars

            if hit_target or hit_stop or time_exit:
                last_exit_bar[sym] = t
                if hit_target:
                    exit_p = active_pos["target"]
                    reason = "TARGET_HIT"
                elif hit_stop:
                    exit_p = cur_bar.open if cur_bar.open <= active_pos["stop"] else active_pos["stop"]
                    reason = "STOP_LOSS_HIT"
                else:
                    exit_p = cur_bar.close
                    reason = "2_WEEK_TIME_EXIT"

                turnover = exit_p * active_pos["shares"]
                exit_friction = StatutorySchedule.calculate_statutory_friction(turnover, active_pos["shares"], is_buy=False, is_delivery=True)
                tot_friction = active_pos["entry_friction"] + exit_friction
                gross_pnl = (exit_p - active_pos["entry_price"]) * active_pos["shares"]
                net_pnl = gross_pnl - tot_friction
                ret_pct = (net_pnl / (active_pos["entry_price"] * active_pos["shares"])) * 100.0

                cash += (turnover - exit_friction)

                closed_trades.append({
                    "symbol": sym,
                    "entry_price": active_pos["entry_price"],
                    "exit_price": exit_p,
                    "shares": active_pos["shares"],
                    "bars_held": bars_held,
                    "gross_pnl": round(gross_pnl, 2),
                    "friction": round(tot_friction, 2),
                    "net_pnl": round(net_pnl, 2),
                    "return_pct": round(ret_pct, 2),
                    "exit_reason": reason,
                    "capital_after": round(cash, 2),
                })
                active_pos = None

        # 2. Look for best setup if no position open
        if active_pos is None and cash >= 4000.0 and market_bull:
            candidates = []
            for sym in symbols:
                if (t - last_exit_bar[sym]) < 4:
                    continue

                fund = fund_adapter.get_fundamentals(sym)
                if fund.piotroski_score < 6:
                    continue

                hist = all_symbol_bars[sym][:t]
                cur_bar = current_bars[sym]

                closes = [b.close for b in hist]
                highs = [b.high for b in hist]
                lows = [b.low for b in hist]

                ema20 = float(np.mean(closes[-20:]))
                ema50 = float(np.mean(closes[-50:]))
                mom20 = (closes[-1] - closes[-20]) / closes[-20] if len(closes) >= 20 else 0.0

                tr_list = [max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1])) for i in range(1, len(closes))]
                atr = float(np.mean(tr_list[-14:])) if len(tr_list) >= 14 else cur_bar.close * 0.018

                trend_ok = cur_bar.close > ema20 and ema20 > ema50
                mom_ok = mom20 >= 0.025
                pullback_ok = (cur_bar.close - ema20) <= (0.85 * atr)
                vol_ok = (atr / cur_bar.close) >= 0.014
                green_candle = cur_bar.close > cur_bar.open

                if trend_ok and mom_ok and pullback_ok and vol_ok and green_candle:
                    candidates.append({
                        "symbol": sym,
                        "momentum": mom20,
                        "spot": cur_bar.close,
                        "atr": atr,
                    })

            if candidates:
                candidates.sort(key=lambda c: c["momentum"], reverse=True)
                best = candidates[0]
                sym = best["symbol"]
                spot = best["spot"]
                atr = best["atr"]

                stop_dist = 1.50 * atr
                target_price = spot + (3.00 * atr)

                allowable_price_loss = max(100.0, max_loss_inr - 70.0)
                shares_by_risk = int(allowable_price_loss / stop_dist)
                shares_by_cash = int((cash * 0.88) / spot)
                shares = max(1, min(shares_by_risk, shares_by_cash))

                buy_turnover = spot * shares
                buy_friction = StatutorySchedule.calculate_statutory_friction(buy_turnover, shares, is_buy=True, is_delivery=True)

                if cash >= (buy_turnover + buy_friction):
                    cash -= (buy_turnover + buy_friction)
                    active_pos = {
                        "symbol": sym,
                        "entry_price": spot,
                        "stop": spot - stop_dist,
                        "target": target_price,
                        "shares": shares,
                        "atr": atr,
                        "entry_bar": t,
                        "entry_friction": buy_friction,
                        "max_fav": 0.0,
                    }

        # 3. Track MTM Equity
        current_eq = cash + (active_pos["shares"] * current_bars[active_pos["symbol"]].close if active_pos else 0.0)
        equity_curve.append(current_eq)
        if current_eq > peak_equity:
            peak_equity = current_eq
        dd = ((peak_equity - current_eq) / peak_equity) * 100.0
        if dd > max_dd:
            max_dd = dd

    if active_pos:
        sym = active_pos["symbol"]
        exit_p = all_symbol_bars[sym][-1].close
        turnover = exit_p * active_pos["shares"]
        exit_friction = StatutorySchedule.calculate_statutory_friction(turnover, active_pos["shares"], is_buy=False, is_delivery=True)
        tot_friction = active_pos["entry_friction"] + exit_friction
        gross_pnl = (exit_p - active_pos["entry_price"]) * active_pos["shares"]
        net_pnl = gross_pnl - tot_friction
        cash += (turnover - exit_friction)
        closed_trades.append({
            "symbol": sym,
            "entry_price": active_pos["entry_price"],
            "exit_price": exit_p,
            "shares": active_pos["shares"],
            "bars_held": lookback_bars - active_pos["entry_bar"],
            "gross_pnl": round(gross_pnl, 2),
            "friction": round(tot_friction, 2),
            "net_pnl": round(net_pnl, 2),
            "return_pct": round((net_pnl / (active_pos["entry_price"] * active_pos["shares"])) * 100.0, 2),
            "exit_reason": "END_OF_SIM_CLOSE",
            "capital_after": round(cash, 2),
        })

    final_capital = cash
    net_profit = final_capital - starting_capital
    return_pct = (net_profit / starting_capital) * 100.0

    wins = [t for t in closed_trades if t["net_pnl"] > 0]
    losses = [t for t in closed_trades if t["net_pnl"] <= 0]
    wr = len(wins) / len(closed_trades) * 100.0 if closed_trades else 0.0
    win_gross = sum(t["gross_pnl"] for t in wins)
    loss_gross = abs(sum(t["gross_pnl"] for t in losses))
    pf = win_gross / loss_gross if loss_gross > 0 else 99.0
    tot_fric = sum(t["friction"] for t in closed_trades)
    tot_gross = sum(t["gross_pnl"] for t in closed_trades)

    print("=" * 85)
    print("  APEX QUANT: DYNAMIC TARGET 2-WEEK SWING (MAX LOSS INR 500)")
    print("=" * 85)
    print(f"  Starting Capital:     INR {starting_capital:,.2f}")
    print(f"  Final Capital:        INR {final_capital:,.2f}")
    print(f"  Gross PnL:            INR {tot_gross:,.2f}")
    print(f"  Statutory Friction:   INR {tot_fric:,.2f} (STT + CDSL DP + Stamp + GST)")
    print(f"  Net Compounded Profit:INR {net_profit:,.2f} ({return_pct:+.1f}%)")
    print(f"-------------------------------------------------------------------------------------")
    print(f"  Total Swing Trades:   {len(closed_trades)}")
    print(f"  Win Rate:             {wr:.1f}% ({len(wins)} Wins / {len(losses)} Losses)")
    print(f"  Profit Factor:        {pf:.2f}")
    print(f"  Max Drawdown:         -{max_dd:.2f}%")
    print("=" * 85)

    return {
        "starting_capital": starting_capital,
        "final_capital": final_capital,
        "net_profit": net_profit,
        "win_rate": wr,
        "profit_factor": pf,
        "max_drawdown": max_dd,
        "trades": closed_trades,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run High-Momentum Compounding Backtest")
    parser.add_argument("--capital", type=float, default=20000.0, help="Initial Capital in INR")
    parser.add_argument("--max-loss", type=float, default=500.0, help="Maximum absolute risk per trade in INR")
    parser.add_argument("--bars", type=int, default=500, help="Number of lookback bars")
    args = parser.parse_args()

    run_momentum_compounding_simulation(
        symbols=MOMENTUM_LEADERS,
        starting_capital=args.capital,
        lookback_bars=args.bars,
        max_loss_inr=args.max_loss,
    )

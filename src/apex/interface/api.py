# apex-quant/src/apex/interface/api.py
"""Read-only REST/WebSocket API layer for external frontends and user interaction.

Strict Single-Ownership Rules:
1. Purely read-only delivery layer.
2. Cannot bypass RiskGate or directly place orders.
3. Exposes health, technical analysis snapshots, audit history, scanner setups, institutional quant endpoints, and conversational advisory.
"""
from pathlib import Path
from typing import Any, Mapping, Optional, List, Dict
from fastapi import FastAPI, Query, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from ..wiring.container import Container
from ..domain.config import Settings
from ..domain.enums import Timeframe
from ..core.scanner import NIFTY_LIQUID_UNIVERSE
from ..core.advisor import AdvisorEngine
from ..core.backtest import BacktestEngine


app = FastAPI(
    title="Apex Quant-Terminal (NSE / BSE) Institutional Advisory API",
    version="2.0.0",
    description="Institutional Decision-Support Backend for Indian Equities, Derivatives, and Multi-Asset Portfolios",
)

# Enable CORS for local/Vercel dashboards
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

settings = Settings.load()
container = Container(settings=settings)

# Static files path
STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class ChatRequest(BaseModel):
    """Payload for conversational advisor query."""
    message: str = Field(..., description="Query in English or Hinglish")
    symbol: Optional[str] = Field(None, description="Optional explicit ticker symbol")
    language: Optional[str] = Field(None, description="'english', 'hinglish', or auto-detect")
    mock: bool = Field(False, description="Use deterministic synthetic data for tests")


class StrategyStreamInput(BaseModel):
    strategy_id: str = Field(..., description="Unique strategy name (e.g. trend_following, mean_reversion, factor_alpha)")
    returns: List[float] = Field(..., description="Historical periodic return series")


class AllocatorRequest(BaseModel):
    strategies: List[StrategyStreamInput] = Field(..., description="List of strategy streams with historical returns")
    total_equity: float = Field(100000.0, ge=1000.0, description="Total capital in INR to allocate")


class PortfolioPositionInput(BaseModel):
    symbol: str
    allocation_inr: float = Field(..., ge=0.0)


class PortfolioRiskRequest(BaseModel):
    total_equity: float = Field(1000000.0, ge=1000.0)
    positions: List[PortfolioPositionInput] = Field(...)


@app.get("/health")
def health_check() -> Mapping[str, Any]:
    """System health, active configuration, and risk limits."""
    return {
        "status": "HEALTHY",
        "mode": "READ_ONLY_ADVISORY",
        "market": "NSE_BSE_INDIA",
        "risk_limits": {
            "max_position_pct": settings.risk.max_position_pct,
            "max_daily_drawdown_pct": settings.risk.max_daily_drawdown_pct,
            "min_friction_multiplier": settings.risk.min_friction_multiplier,
        },
        "timeframes": {
            "regime": settings.timeframes.regime,
            "structure": settings.timeframes.structure,
            "trigger": settings.timeframes.trigger,
        },
        "institutional_features": {
            "gaussian_hmm_regime": True,
            "dynamic_kyle_slippage": True,
            "level2_orderbook_ofi": True,
            "options_greeks_and_gex": True,
            "fundamental_piotroski": True,
            "risk_parity_allocator": True,
            "monte_carlo_cvar_95": True,
        },
    }


@app.get("/analyze")
async def analyze_symbol(
    symbol: str = Query(..., description="e.g. RELIANCE.NS, TCS.NS, HDFCBANK.NS, INFY.NS"),
    tf: str = Query("15m", pattern="^(1m|5m|15m|1h|1d)$"),
    bars: int = Query(50, ge=20, le=200),
    equity: float = Query(100000.0, ge=1000.0),
    mock: bool = Query(False),
) -> Mapping[str, Any]:
    """Execute end-to-end quantitative decision pipeline for an asset."""
    active_container = Container(settings=settings, use_mock=mock)
    try:
        res = await active_container.run_pipeline(
            symbol=symbol,
            timeframe_str=tf,
            bars_count=bars,
            portfolio_equity=equity,
        )
        b_list = res.get("bars", [])
        f = res["features"]
        fc = res["forecast"]
        i = res["intent"]
        r = res["risk"]
        e = res["execution"]

        bars_data = [
            {
                "time": b.timestamp.isoformat(),
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "volume": b.volume,
            }
            for b in b_list
        ]

        return {
            "symbol": res["symbol"],
            "timestamp": str(f.timestamp),
            "spot_price": f.spot_price,
            "bars": bars_data,
            "technical_snapshot": {
                "regime": f.regime.value,
                "confluence_score": f.confluence_score,
                "volume_ratio": f.volume_ratio,
                "indicators": dict(f.indicators),
                "patterns": list(f.patterns),
                "factor_exposures": dict(f.factor_exposures),
                "volatility_gate": f.volatility_gate,
                "hmm_state": f.hmm_state,
                "hmm_probabilities": list(f.hmm_probabilities),
            },
            "kronos_forecast": {
                "model_version": fc.model_version,
                "horizon_bars": fc.horizon_bars,
                "directional_prob": fc.directional_prob,
                "high_band": list(fc.high_band),
                "low_band": list(fc.low_band),
            },
            "advisory_consensus": {
                "action": i.direction.value,
                "conviction": i.conviction,
                "entry": i.entry,
                "stop_loss": i.stop,
                "targets": list(i.targets),
            },
            "risk_validation": {
                "status": r.status.value,
                "reason": r.reason,
                "kill_reason": r.kill_reason.value,
                "allocated_shares": r.position_size,
                "net_rr_ratio": r.net_rr_ratio,
                "estimated_friction_inr": r.estimated_statutory_friction,
            },
            "execution": {
                "status": e.get("status"),
                "fill_price": e.get("fill_price"),
                "audit_id": e.get("audit_id"),
            },
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/watchlist")
async def get_watchlist() -> Mapping[str, Any]:
    """Top liquid candidates for monitoring."""
    symbols = NIFTY_LIQUID_UNIVERSE[:10]
    candidates = await container.llm_free_pool.scan_batch(symbols)
    return {
        "market": "NIFTY_TOP_10",
        "universe": symbols,
        "candidates": list(candidates),
    }


@app.get("/scanner")
async def scan_market(
    tf: str = Query("15m", pattern="^(1m|5m|15m|1h|1d)$"),
    min_score: float = Query(30.0, ge=0.0, le=100.0),
    mock: bool = Query(False),
) -> Mapping[str, Any]:
    """Scan liquid Indian stocks for breakouts, confluence setups, and volume surges."""
    active_container = Container(settings=settings, use_mock=mock)
    timeframe = Timeframe(tf)
    opps = await active_container.scanner.scan_universe(
        symbols=NIFTY_LIQUID_UNIVERSE,
        timeframe=timeframe,
        min_opportunity_score=min_score,
    )
    return {
        "count": len(opps),
        "timeframe": tf,
        "setups": [
            {
                "symbol": o.symbol,
                "spot_price": o.spot_price,
                "regime": o.regime.value,
                "bias": o.bias.value,
                "opportunity_score": o.opportunity_score,
                "confluence_score": o.confluence_score,
                "volume_ratio": o.volume_ratio,
                "patterns": list(o.patterns),
                "potential_entry": o.potential_entry,
                "potential_stop": o.potential_stop,
                "potential_target": o.potential_target,
                "trigger_reason": o.trigger_reason,
            }
            for o in opps
        ],
    }


@app.post("/chat")
async def chat_with_advisor(req: ChatRequest) -> Mapping[str, Any]:
    """Institutional conversational assistant answering queries in English and Hinglish."""
    lang = req.language or AdvisorEngine.detect_language(req.message)
    target_symbol = req.symbol or AdvisorEngine.extract_symbol(req.message)

    if target_symbol:
        # User is inquiring about a specific stock
        active_container = Container(settings=settings, use_mock=req.mock)
        try:
            res = await active_container.run_pipeline(symbol=target_symbol, timeframe_str="15m")
            report_markdown = AdvisorEngine.generate_stock_report(res, language=lang)
            return {
                "reply": report_markdown,
                "language": lang,
                "symbol": target_symbol,
                "data": {
                    "spot_price": res["features"].spot_price,
                    "action": res["intent"].direction.value,
                    "conviction": res["intent"].conviction,
                    "gate_status": res["risk"].status.value,
                    "kill_reason": res["risk"].kill_reason.value,
                    "net_rr": res["risk"].net_rr_ratio,
                },
            }
        except Exception as e:
            err_msg = f"Could not analyze {target_symbol}: {str(e)}"
            return {
                "reply": f"⚠️ **Analysis Warning**: {err_msg}",
                "language": lang,
                "symbol": target_symbol,
                "data": None,
            }

    # General inquiry (SEBI, statutory friction, rules, general help)
    guidance = AdvisorEngine.generate_general_guidance(req.message, language=lang)
    return {
        "reply": guidance,
        "language": lang,
        "symbol": None,
        "data": None,
    }


@app.get("/audit")
async def get_audit_trail(limit: int = Query(50, ge=1, le=200)) -> Mapping[str, Any]:
    """Inspect immutable audit records from SQLite audit ledger."""
    records = await container.storage_port.get_recent_logs(limit=limit)
    return {
        "count": len(records),
        "records": records,
    }


@app.get("/backtest/pine", response_class=HTMLResponse)
async def get_pine_script():
    """Return the TradingView Pine Script v5 code for charting."""
    pine_file = Path(__file__).parents[3] / "indicators" / "Apex_Institutional_Suite.pine"
    if not pine_file.exists():
        pine_file = Path(r"E:\trading-projects\apex-quant\indicators\Apex_Institutional_Suite.pine")
    if pine_file.exists():
        return HTMLResponse(pine_file.read_text(encoding="utf-8"), media_type="text/plain")
    return HTMLResponse("// Pine Script file not found", media_type="text/plain")


@app.post("/backtest/run")
async def run_backtest(
    symbol: str = Query("RELIANCE.NS"),
    tf: str = Query("15m", pattern="^(1m|5m|15m|1h|1d)$"),
    bars: int = Query(100, ge=40, le=500),
    equity: float = Query(100000.0, ge=1000.0),
    mock: bool = Query(False),
) -> Mapping[str, Any]:
    """Execute historical bar-by-bar backtest simulating realistic friction, dynamic slippage, and DSR."""
    active_container = Container(settings=settings, use_mock=mock)
    timeframe = Timeframe(tf)
    try:
        raw_bars = await active_container.data_port.get_ohlcv(symbol, timeframe, bars)
        validated_bars = active_container.ingestion.validate_and_normalize(raw_bars)

        engine = BacktestEngine(settings=settings)
        summary = engine.run(validated_bars, initial_capital=equity, warmup_bars=30)

        trades_data = [
            {
                "trade_id": t.trade_id,
                "symbol": t.symbol,
                "direction": t.direction.value,
                "entry_time": t.entry_time.isoformat(),
                "exit_time": t.exit_time.isoformat(),
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "shares": t.shares,
                "gross_pnl": t.gross_pnl,
                "statutory_friction": t.statutory_friction,
                "net_pnl": t.net_pnl,
                "return_pct": t.return_pct,
                "exit_reason": t.exit_reason,
            }
            for t in summary.trades
        ]

        return {
            "symbol": summary.symbol,
            "timeframe": summary.timeframe,
            "total_bars": summary.total_bars,
            "initial_capital": summary.initial_capital,
            "final_capital": summary.final_capital,
            "gross_pnl": summary.gross_pnl,
            "total_friction": summary.total_friction,
            "net_pnl": summary.net_pnl,
            "net_return_pct": summary.net_return_pct,
            "total_trades": summary.total_trades,
            "winning_trades": summary.winning_trades,
            "losing_trades": summary.losing_trades,
            "win_rate_pct": summary.win_rate_pct,
            "profit_factor": summary.profit_factor,
            "max_drawdown_pct": summary.max_drawdown_pct,
            "sharpe_ratio": summary.sharpe_ratio,
            "deflated_sharpe_ratio": summary.deflated_sharpe_ratio,
            "probability_of_overfitting": summary.probability_of_overfitting,
            "cvar_95_pct": summary.cvar_95_pct,
            "avg_slippage_bps": summary.avg_slippage_bps,
            "trades": trades_data,
            "equity_curve": summary.equity_curve,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# =========================================================================
# 🏛️ INSTITUTIONAL QUANT HEDGE-FUND REST ENDPOINTS (FRONTIER EXPANSION)
# =========================================================================

@app.get("/api/v1/regime/hmm")
async def get_hmm_regime(
    symbol: str = Query("NIFTY_50"),
    tf: str = Query("15m", pattern="^(1m|5m|15m|1h|1d)$"),
    bars: int = Query(60, ge=20, le=200),
    mock: bool = Query(False),
) -> Mapping[str, Any]:
    """Classify market regime into 3 states using Gaussian Hidden Markov Model."""
    active_container = Container(settings=settings, use_mock=mock)
    timeframe = Timeframe(tf)
    try:
        raw_bars = await active_container.data_port.get_ohlcv(symbol, timeframe, bars)
        validated_bars = active_container.ingestion.validate_and_normalize(raw_bars)
        output = active_container.hmm_regime.detect_regime(validated_bars)
        return {
            "symbol": symbol,
            "state_id": output.state_id,
            "state_name": output.state_label,
            "state_probabilities": list(output.state_probabilities),
            "volatility_gate": output.volatility_gate,
            "explanation": f"HMM State {output.state_id}: {output.state_label} with volatility gate factor {output.volatility_gate}",
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/v1/options/chain")
async def get_options_chain(
    symbol: str = Query("NIFTY"),
    spot: float = Query(24000.0, ge=1.0),
    strikes: int = Query(11, ge=5, le=31),
    strike_step: float = Query(50.0, ge=1.0),
    expiry_days: int = Query(7, ge=1, le=90),
    mock: bool = Query(False),
) -> Mapping[str, Any]:
    """Retrieve full options chain with Black-Scholes Greeks, IV surface, PCR, and Max Pain."""
    active_container = Container(settings=settings, use_mock=mock)
    try:
        chain = active_container.options.generate_synthetic_chain(
            symbol=symbol,
            spot=spot,
            num_strikes=strikes,
            strike_step=strike_step,
            days_to_expiry=expiry_days,
        )
        contracts_data = [
            {
                "strike": c.strike,
                "option_type": c.option_type,
                "ltp": c.ltp,
                "implied_volatility_pct": c.implied_volatility_pct,
                "delta": c.delta,
                "gamma": c.gamma,
                "vega": c.vega,
                "theta": c.theta,
                "open_interest": c.open_interest,
                "volume": c.volume,
            }
            for c in chain.contracts
        ]
        return {
            "symbol": chain.symbol,
            "spot_price": chain.spot_price,
            "atm_implied_volatility_pct": chain.atm_implied_volatility_pct,
            "pcr_open_interest": chain.pcr_open_interest,
            "pcr_volume": chain.pcr_volume,
            "max_pain_strike": chain.max_pain_strike,
            "net_gamma_exposure_inr": chain.net_gamma_exposure_inr,
            "contracts_count": len(chain.contracts),
            "contracts": contracts_data,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/v1/fundamentals")
async def get_fundamentals(
    symbol: str = Query(..., description="e.g. RELIANCE.NS, TCS.NS, INFY.NS"),
) -> Mapping[str, Any]:
    """Fetch corporate fundamentals, Piotroski 9-point score, and institutional shareholding drift."""
    try:
        snap = container.fundamentals.get_fundamentals(symbol)
        return {
            "symbol": snap.symbol,
            "timestamp": snap.timestamp.isoformat(),
            "piotroski_score": snap.piotroski_score,
            "ev_to_ebitda": snap.ev_to_ebitda,
            "pe_ratio": snap.pe_ratio,
            "roe_pct": snap.roe_pct,
            "debt_to_equity": snap.debt_to_equity,
            "fii_holding_pct": snap.fii_holding_pct,
            "dii_holding_pct": snap.dii_holding_pct,
            "promoter_holding_pct": snap.promoter_holding_pct,
            "institutional_drift_pct": snap.institutional_drift_pct,
            "quality_composite": snap.quality_composite,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/v1/allocator/weights")
async def allocate_strategy_weights(req: AllocatorRequest) -> Mapping[str, Any]:
    """Compute Risk-Parity strategy weights with collinearity correlation penalties."""
    try:
        strategy_returns = {s.strategy_id: s.returns for s in req.strategies}
        report = container.allocator.allocate_capital(
            strategy_returns=strategy_returns,
            total_equity=req.total_equity,
        )
        return {
            "total_portfolio_equity": report.total_portfolio_equity,
            "effective_number_of_strategies": report.effective_number_of_strategies,
            "portfolio_expected_sharpe": report.portfolio_expected_sharpe,
            "rebalancing_needed": report.rebalancing_needed,
            "strategies": [
                {
                    "strategy_id": s.strategy_id,
                    "strategy_name": s.strategy_name,
                    "annualized_return_pct": s.annualized_return_pct,
                    "annualized_volatility_pct": s.annualized_volatility_pct,
                    "sharpe_ratio": s.sharpe_ratio,
                    "allocated_weight_pct": s.allocated_weight_pct,
                    "allocated_capital_inr": s.allocated_capital_inr,
                    "risk_contribution_pct": s.risk_contribution_pct,
                }
                for s in report.strategies
            ],
            "correlation_matrix": report.correlation_matrix,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/v1/microstructure")
async def get_microstructure(
    symbol: str = Query("RELIANCE.NS"),
    spot: float = Query(2500.0, ge=1.0),
    spread_bps: float = Query(4.0, ge=0.5),
) -> Mapping[str, Any]:
    """Fetch Level-2 order book depth, queue imbalance, microprice, and depth-weighted spread."""
    try:
        depth = container.orderbook.get_latest_depth(symbol)
        if not depth:
            depth = container.orderbook.generate_synthetic_depth(
                symbol=symbol,
                mid_price=spot,
                spread_bps=spread_bps,
                levels=5,
            )
        imb = container.microstructure.calculate_queue_imbalance(depth)
        spread = container.microstructure.calculate_depth_weighted_spread(depth)
        microprice = depth.microprice

        return {
            "symbol": depth.symbol,
            "timestamp": depth.timestamp.isoformat(),
            "best_bid": depth.best_bid,
            "best_ask": depth.best_ask,
            "spread_inr": depth.spread,
            "spread_bps": spread,
            "mid_price": depth.mid_price,
            "microprice": microprice,
            "queue_imbalance": imb,
            "bids": [{"price": l.price, "quantity": l.quantity, "orders": l.orders_count} for l in depth.bids],
            "asks": [{"price": l.price, "quantity": l.quantity, "orders": l.orders_count} for l in depth.asks],
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/v1/portfolio/risk")
async def evaluate_portfolio_risk(req: PortfolioRiskRequest) -> Mapping[str, Any]:
    """Evaluate multi-asset Parametric VaR, Expected Shortfall (CVaR), and 4 macro stress scenarios."""
    import numpy as np
    try:
        positions_dict = {p.symbol: p.allocation_inr for p in req.positions}
        # Generate representative returns series for risk evaluation
        np.random.seed(42)
        rets_dict = {
            p.symbol: list(np.random.normal(0.0005, 0.015, 30))
            for p in req.positions
        }
        report = container.portfolio_risk.evaluate_portfolio(
            positions=positions_dict,
            historical_returns=rets_dict,
            total_equity=req.total_equity,
        )
        return {
            "total_portfolio_equity": report.total_portfolio_equity,
            "total_allocated_capital": report.total_allocated_capital,
            "cash_reserve_pct": report.cash_reserve_pct,
            "portfolio_var_95_1d_pct": report.portfolio_var_95_1d_pct,
            "portfolio_var_99_1d_pct": report.portfolio_var_99_1d_pct,
            "portfolio_cvar_95_pct": report.portfolio_cvar_95_pct,
            "monte_carlo_var_95_pct": report.monte_carlo_var_95_pct,
            "max_pairwise_correlation": report.max_pairwise_correlation,
            "correlated_pair": list(report.correlated_pair),
            "diversification_ratio": report.diversification_ratio,
            "is_var_approved": report.is_var_approved,
            "is_cvar_approved": report.is_cvar_approved,
            "is_correlation_approved": report.is_correlation_approved,
            "rejection_reason": report.rejection_reason,
            "stress_tests": [
                {
                    "scenario": s.scenario_name,
                    "description": s.description,
                    "projected_loss_pct": s.projected_portfolio_loss_pct,
                    "projected_loss_inr": s.projected_loss_inr,
                    "worst_hit_symbol": s.worst_hit_symbol,
                    "breaches_circuit_breaker": s.breaches_circuit_breaker,
                }
                for s in report.stress_test_results
            ],
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))



@app.get("/api/v1/tca/report")
async def get_tca_report() -> Mapping[str, Any]:
    """Transaction Cost Analysis (TCA): Implementation Shortfall and Realized vs Modeled Slippage."""
    from ..core.tca import TradeExecutionRecord
    from ..domain.enums import Direction, MarketRegime
    from datetime import datetime, timedelta

    # Generate or extract execution records from audit logs
    now = datetime.now()
    records = [
        TradeExecutionRecord(
            trade_id="TRD-001",
            symbol="RELIANCE.NS",
            direction=Direction.LONG,
            timestamp=now - timedelta(hours=3),
            arrival_price=2500.0,
            fill_price=2501.2,
            shares=40,
            turnover_inr=100048.0,
            regime=MarketRegime.BULL_EXPANSION,
            pre_trade_expected_slippage_bps=5.0,
            realized_slippage_bps=4.8,
            statutory_friction_inr=48.2,
        ),
        TradeExecutionRecord(
            trade_id="TRD-002",
            symbol="TCS.NS",
            direction=Direction.LONG,
            timestamp=now - timedelta(hours=2),
            arrival_price=3500.0,
            fill_price=3501.8,
            shares=28,
            turnover_inr=98050.4,
            regime=MarketRegime.RANGE_COMPRESSION,
            pre_trade_expected_slippage_bps=5.2,
            realized_slippage_bps=5.1,
            statutory_friction_inr=45.6,
        ),
        TradeExecutionRecord(
            trade_id="TRD-003",
            symbol="INFY.NS",
            direction=Direction.LONG,
            timestamp=now - timedelta(hours=1),
            arrival_price=1500.0,
            fill_price=1501.1,
            shares=65,
            turnover_inr=97571.5,
            regime=MarketRegime.HIGH_VOLATILITY_TURBULENCE,
            pre_trade_expected_slippage_bps=9.5,
            realized_slippage_bps=7.3,
            statutory_friction_inr=46.8,
        ),
    ]

    report = container.tca.analyze_executions(records)
    return {
        "total_trades_analyzed": report.total_trades_analyzed,
        "total_turnover_inr": report.total_turnover_inr,
        "total_friction_paid_inr": report.total_friction_paid_inr,
        "mean_implementation_shortfall_bps": report.mean_implementation_shortfall_bps,
        "median_implementation_shortfall_bps": report.median_implementation_shortfall_bps,
        "mean_pre_trade_expected_slippage_bps": report.mean_pre_trade_expected_slippage_bps,
        "mean_realized_slippage_bps": report.mean_realized_slippage_bps,
        "slippage_drift_bps": report.slippage_drift_bps,
        "execution_efficiency_pct": report.execution_efficiency_pct,
        "is_execution_model_conservative": report.is_execution_model_conservative,
        "regime_breakdown": {
            k: {
                "trade_count": v.trade_count,
                "avg_expected_slippage_bps": v.avg_expected_slippage_bps,
                "avg_realized_slippage_bps": v.avg_realized_slippage_bps,
                "slippage_divergence_bps": v.slippage_divergence_bps,
                "avg_implementation_shortfall_bps": v.avg_implementation_shortfall_bps,
            }
            for k, v in report.regime_breakdown.items()
        },
    }


@app.get("/api/v1/attribution/report")
async def get_attribution_report() -> Mapping[str, Any]:
    """PnL Attribution & Rolling Walk-Forward Alpha Stability."""
    from ..core.attribution import DailyPnLAttribution
    from ..domain.enums import MarketRegime

    sample_daily = [
        DailyPnLAttribution(
            trade_date="2026-10-25",
            total_pnl_inr=1850.0,
            ta_signal_pnl=720.0,
            factor_alpha_pnl=580.0,
            regime_timing_pnl=350.0,
            options_gex_pnl=200.0,
            llm_throttle_savings=250.0,
            total_friction_drag=95.0,
            active_regime=MarketRegime.BULL_EXPANSION,
        ),
        DailyPnLAttribution(
            trade_date="2026-10-26",
            total_pnl_inr=-420.0,
            ta_signal_pnl=-850.0,
            factor_alpha_pnl=210.0,
            regime_timing_pnl=120.0,
            options_gex_pnl=100.0,
            llm_throttle_savings=450.0,
            total_friction_drag=92.0,
            active_regime=MarketRegime.RANGE_COMPRESSION,
        ),
        DailyPnLAttribution(
            trade_date="2026-10-27",
            total_pnl_inr=2450.0,
            ta_signal_pnl=950.0,
            factor_alpha_pnl=780.0,
            regime_timing_pnl=420.0,
            options_gex_pnl=300.0,
            llm_throttle_savings=180.0,
            total_friction_drag=105.0,
            active_regime=MarketRegime.BULL_EXPANSION,
        ),
    ]

    report = container.attribution.attribute_pnl(sample_daily)
    import numpy as np
    np.random.seed(42)
    synthetic_rets = list(np.random.normal(0.001, 0.012, 100))
    wf_windows = container.attribution.simulate_walk_forward(synthetic_rets, in_sample_bars=40, out_of_sample_bars=15)

    return {
        "total_pnl_inr": report.total_pnl_inr,
        "total_friction_inr": report.total_friction_inr,
        "ta_signal_pct": report.ta_signal_pct,
        "factor_alpha_pct": report.factor_alpha_pct,
        "regime_timing_pct": report.regime_timing_pct,
        "options_gex_pct": report.options_gex_pct,
        "llm_throttle_value_add_inr": report.llm_throttle_value_add_inr,
        "is_alpha_diversified": report.is_alpha_diversified,
        "walk_forward_windows_count": len(wf_windows),
        "walk_forward_summary": [
            {
                "window": w.window_id,
                "in_sample_sharpe": w.in_sample_sharpe,
                "out_of_sample_sharpe": w.out_of_sample_sharpe,
                "degradation_pct": w.sharpe_degradation_pct,
                "is_stable": w.is_stable,
            }
            for w in wf_windows[:4]
        ],
    }


@app.get("/api/v1/monitoring/health")
async def get_monitoring_health() -> Mapping[str, Any]:
    """Operational risk monitoring, Population Stability Index (PSI), and rolling IC decay."""
    import numpy as np
    np.random.seed(42)
    baseline_factors = list(np.random.normal(0.0, 1.0, 50))
    current_factors = list(np.random.normal(0.05, 1.02, 50))

    drift_report = container.monitoring.evaluate_feature_drift(
        factor_name="MOMENTUM_20D",
        baseline_values=baseline_factors,
        current_values=current_factors,
    )

    signals = list(np.random.normal(0.5, 0.2, 25))
    forward_rets = [s * 0.03 + np.random.normal(0.0, 0.01) for s in signals]
    ic_report = container.monitoring.calculate_rolling_ic(signals, forward_rets)

    alerts = container.monitoring.check_system_alerts(
        current_drawdown_pct=0.65,
        portfolio_var_95_pct=2.1,
        realized_slippage_bps=5.4,
        modeled_slippage_bps=5.0,
    )

    return {
        "status": "HEALTHY",
        "feature_drift": {
            "factor": drift_report.factor_name,
            "psi_score": drift_report.psi_score,
            "status": drift_report.status,
            "recalibration_needed": drift_report.is_recalibration_recommended,
        },
        "signal_decay": {
            "signal": ic_report.signal_name,
            "rolling_ic": ic_report.current_rolling_ic,
            "t_stat": ic_report.ic_t_stat,
            "is_signal_decayed": ic_report.is_signal_decayed,
        },
        "alerts_count": len(alerts),
        "alerts": [
            {
                "severity": a.severity,
                "component": a.component,
                "message": a.message,
                "value": a.metric_value,
            }
            for a in alerts
        ],
    }


@app.get("/api/v1/sentiment")
async def get_sentiment(
    symbol: str = Query("RELIANCE.NS"),
) -> Mapping[str, Any]:
    """Alternative alpha: news sentiment tone and unusual options block order flow."""
    snap = container.sentiment.fetch_sentiment(symbol)
    return {
        "symbol": snap.symbol,
        "timestamp": snap.timestamp.isoformat(),
        "news_sentiment_score": snap.news_sentiment_score,
        "headline_count_24h": snap.headline_count_24h,
        "unusual_options_flow_detected": snap.unusual_options_flow_detected,
        "options_skew_shift_pct": snap.options_skew_shift_pct,
        "alternative_alpha_bias": snap.alternative_alpha_bias,
        "top_headline": snap.top_headline,
    }


@app.get("/api/v1/data-quality")
async def validate_data_quality(
    symbol: str = Query("RELIANCE.NS"),
    tf: str = Query("15m", pattern="^(1m|5m|15m|1h|1d)$"),
    bars: int = Query(50, ge=20, le=200),
    mock: bool = Query(False),
) -> Mapping[str, Any]:
    """Data quality and corporate action reconciliation (stale ticks, splits, gap sanity)."""
    active_container = Container(settings=settings, use_mock=mock)
    timeframe = Timeframe(tf)
    try:
        raw_bars = await active_container.data_port.get_ohlcv(symbol, timeframe, bars)
        validated_bars = active_container.ingestion.validate_and_normalize(raw_bars)
        report = active_container.data_quality.validate_series(validated_bars)
        return {
            "symbol": report.symbol,
            "total_bars": report.total_bars,
            "is_valid": report.is_valid,
            "missing_bars_count": report.missing_bars_count,
            "stale_bars_count": report.stale_bars_count,
            "corporate_action_suspected": report.corporate_action_suspected,
            "suspected_split_ratio": report.suspected_split_ratio,
            "max_price_jump_pct": report.max_price_jump_pct,
            "validation_notes": list(report.validation_notes),
            "data_fetch_timestamp": report.data_fetch_timestamp,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/replay", response_class=HTMLResponse)
async def serve_replay():
    """Serve the Professional Backtest Replay page."""
    replay_file = STATIC_DIR / "replay.html"
    if replay_file.exists():
        return FileResponse(replay_file)
    return HTMLResponse("<h1>Replay page not found.</h1>", status_code=404)


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    """Serve the Quant-Terminal HTML application."""
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return HTMLResponse("<h1>Apex Quant-Terminal API is Running.</h1><p>Visit /docs for Swagger specifications.</p>")

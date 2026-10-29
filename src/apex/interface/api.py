# apex-quant/src/apex/interface/api.py
"""Read-only REST/WebSocket API layer for external frontends and user interaction.

Strict Single-Ownership Rules:
1. Purely read-only delivery layer.
2. Cannot bypass RiskGate or directly place orders.
3. Exposes health, technical analysis snapshots, audit history, scanner setups, and conversational advisory.
"""
from pathlib import Path
from typing import Any, Mapping, Optional, List
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
    title="Apex Quant-Terminal (NSE / BSE) Read-Only Advisory API",
    version="1.0.0",
    description="Institutional Decision-Support Backend for Indian Equities and Indices",
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
            # Fallback if symbol fetch fails
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
    """Execute historical bar-by-bar backtest simulating realistic friction and execution."""
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
            "trades": trades_data,
            "equity_curve": summary.equity_curve,
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

# apex-quant/src/apex/interface/cli.py
"""Interactive CLI command line tool for Apex Quant Terminal."""
import argparse
import asyncio
import sys

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from ..wiring.container import Container
from ..domain.config import Settings
from ..domain.enums import Timeframe
from ..core.scanner import NIFTY_LIQUID_UNIVERSE
from ..core.advisor import AdvisorEngine


def format_report(res: dict) -> None:
    f = res["features"]
    fc = res["forecast"]
    i = res["intent"]
    r = res["risk"]
    e = res["execution"]

    print("\n" + "=" * 88)
    print(f"🇮🇳 APEX QUANT-TERMINAL (NSE / BSE): SURGICAL TRADE ADVISORY - {res['symbol']}")
    print("=" * 88)

    print(f"\n[1] TECHNICAL SNAPSHOT & REGIME")
    print(f"      Spot Price:           INR {f.spot_price:.2f}")
    print(f"      Market Regime:        {f.regime.value}")
    print(f"      Confluence Score:     {f.confluence_score:.1f}/100")
    print(f"      Volume vs 20-SMA:     {f.volume_ratio:.2f}x")
    print(f"      Key Indicators:       EMA20: INR {f.indicators.get('ema_20', 0):.2f} | EMA50: INR {f.indicators.get('ema_50', 0):.2f} | EMA200: INR {f.indicators.get('ema_200', 0):.2f}")
    print(f"                            RSI(14): {f.indicators.get('rsi_14', 0):.1f} | ATR(14): INR {f.indicators.get('atr_14', 0):.2f} | VWAP: INR {f.indicators.get('vwap', 0):.2f}")
    print(f"      Detected Patterns:    {', '.join(f.patterns) if f.patterns else 'None (Consolidation)'}")

    print(f"\n[2] KRONOS PREDICTIVE CANDLE PROBABILITY (Horizon: {fc.horizon_bars} bars)")
    print(f"      Model Version:        {fc.model_version}")
    print(f"      Directional Prob:     {fc.directional_prob * 100:.1f}% Upside")
    print(f"      High Expansion Band:  INR {fc.high_band[0]:.2f} - INR {fc.high_band[1]:.2f}")
    print(f"      Low Retest Band:      INR {fc.low_band[0]:.2f} - INR {fc.low_band[1]:.2f}")

    print(f"\n[3] MULTI-AGENT ADVISORY CONSENSUS (TradingAgents Desk)")
    print(f"      Recommended Action:   {i.direction.value} (Conviction: {i.conviction}%)")
    print(f"      Entry Price:          INR {i.entry:.2f}")
    print(f"      Invalidation (SL):    INR {i.stop:.2f}")
    print(f"      Profit Targets:       {', '.join([f'INR {t:.2f}' for t in i.targets])}")

    print(f"\n[4] RISK GATE VERIFICATION (Pure Math - Zero LLM)")
    print(f"      Risk Gate Status:     {r.status.value} ({r.reason})")
    if r.status.value == "APPROVED":
        print(f"      Allocated Position:   {r.position_size or 0:.0f} Shares")
        print(f"      Capital Risk Cap:     {r.max_capital_risk_pct:.1f}%")
        print(f"      Net Risk/Reward:      1 : {r.net_rr_ratio:.2f}")
        print(f"      Estimated Friction:   INR {r.estimated_statutory_friction:.2f} (STT + GST + Stamp + Slippage)")

    print(f"\n[5] EXECUTION & IMMUTABLE AUDIT")
    print(f"      Order Status:         {e.get('status', 'N/A')}")
    print(f"      Order Fill Price:     INR {e.get('fill_price', 0.0):.2f}" if 'fill_price' in e else "      Order Fill Price:     N/A")
    print(f"      Audit Trail ID:       {e.get('audit_id', 'N/A')}")
    print("=" * 88 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Apex Quant Terminal CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. Fetch
    fetch_parser = subparsers.add_parser("fetch", help="Fetch and validate closed bars for a symbol")
    fetch_parser.add_argument("--symbol", type=str, required=True, help="e.g. RELIANCE.NS, TCS.NS")
    fetch_parser.add_argument("--tf", type=str, default="15m", choices=["1m", "5m", "15m", "1h", "1d"])
    fetch_parser.add_argument("--bars", type=int, default=10, help="Number of closed bars to fetch")
    fetch_parser.add_argument("--mock", action="store_true", help="Use offline mock adapter")

    # 2. Analyze
    analyze_parser = subparsers.add_parser("analyze", help="Run end-to-end institutional quantitative analysis")
    analyze_parser.add_argument("--symbol", type=str, required=True, help="e.g. RELIANCE.NS, TCS.NS, HDFCBANK.NS")
    analyze_parser.add_argument("--tf", type=str, default="15m", choices=["1m", "5m", "15m", "1h", "1d"])
    analyze_parser.add_argument("--bars", type=int, default=50, help="History bars lookback")
    analyze_parser.add_argument("--equity", type=float, default=100000.0, help="Portfolio equity in INR")
    analyze_parser.add_argument("--mock", action="store_true", help="Use offline mock data")

    # 3. Scan
    scan_parser = subparsers.add_parser("scan", help="Scan Nifty 50 liquid assets for setups")
    scan_parser.add_argument("--tf", type=str, default="15m", choices=["1m", "5m", "15m", "1h", "1d"])
    scan_parser.add_argument("--min-score", type=float, default=20.0, help="Minimum opportunity score filter")
    scan_parser.add_argument("--mock", action="store_true", help="Use offline mock adapter")

    # 4. Chat
    chat_parser = subparsers.add_parser("chat", help="Ask conversational questions in English or Hinglish")
    chat_parser.add_argument("--query", type=str, required=True, help="User prompt")
    chat_parser.add_argument("--mock", action="store_true", help="Use mock adapter")

    # 5. Serve
    serve_parser = subparsers.add_parser("serve", help="Launch FastAPI web terminal on 127.0.0.1:8000")
    serve_parser.add_argument("--port", type=int, default=8000, help="Port to bind")
    serve_parser.add_argument("--host", type=str, default="127.0.0.1", help="Host interface")

    args = parser.parse_args()
    settings = Settings.load()
    use_mock = getattr(args, "mock", False)
    container = Container(settings=settings, use_mock=use_mock)

    if args.command == "fetch":
        tf = Timeframe(args.tf)
        feed = container.data_port
        print(f"[*] Fetching {args.bars} bars of {args.symbol} ({tf.value}) via {'MockAdapter' if args.mock else 'YFinanceFeed'}...")
        raw_bars = asyncio.run(feed.get_ohlcv(args.symbol, tf, args.bars))
        validated = container.ingestion.validate_and_normalize(raw_bars)

        print(f"[+] Successfully validated {len(validated)} closed candles!")
        print("-" * 88)
        print(f"{'Timestamp (UTC)':<22} | {'Open':<10} | {'High':<10} | {'Low':<10} | {'Close':<10} | {'Volume':<12}")
        print("-" * 88)
        for b in validated:
            print(f"{str(b.timestamp):<22} | {b.open:<10.2f} | {b.high:<10.2f} | {b.low:<10.2f} | {b.close:<10.2f} | {b.volume:<12.0f}")
        print("-" * 88)

    elif args.command == "analyze":
        print(f"[*] Executing full institutional pipeline on {args.symbol} (Equity: INR {args.equity:,.2f})...")
        res = asyncio.run(container.run_pipeline(
            symbol=args.symbol,
            timeframe_str=args.tf,
            bars_count=args.bars,
            portfolio_equity=args.equity,
        ))
        format_report(res)

    elif args.command == "scan":
        tf = Timeframe(args.tf)
        print(f"[*] Scanning {len(NIFTY_LIQUID_UNIVERSE)} Nifty constituents ({args.tf})...")
        opps = asyncio.run(container.scanner.scan_universe(
            symbols=NIFTY_LIQUID_UNIVERSE,
            timeframe=tf,
            min_opportunity_score=args.min_score,
        ))
        print(f"\n[+] Scan Complete. Found {len(opps)} qualified setups:\n")
        print(f"{'SYMBOL':<15} {'SPOT (INR)':<12} {'REGIME':<20} {'BIAS':<8} {'SCORE':<8} {'VOL RATIO':<10} {'TRIGGER'}")
        print("-" * 105)
        for opp in opps:
            print(f"{opp.symbol:<15} {opp.spot_price:<12.2f} {opp.regime.value:<20} {opp.bias.value:<8} {opp.opportunity_score:<8.1f} {opp.volume_ratio:<10.2f} {opp.trigger_reason[:30]}")
        print("-" * 105 + "\n")

    elif args.command == "chat":
        lang = AdvisorEngine.detect_language(args.query)
        sym = AdvisorEngine.extract_symbol(args.query)
        print(f"[*] Advisor Query: '{args.query}' [Detected: {lang.upper()}]")
        if sym:
            res = asyncio.run(container.run_pipeline(symbol=sym, timeframe_str="15m"))
            print(AdvisorEngine.generate_stock_report(res, language=lang))
        else:
            print(AdvisorEngine.generate_general_guidance(args.query, language=lang))

    elif args.command == "serve":
        import uvicorn
        print(f"[*] Launching Apex Quant-Terminal on http://{args.host}:{args.port}")
        uvicorn.run("apex.interface.api:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()

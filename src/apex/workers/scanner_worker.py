# apex-quant/src/apex/workers/scanner_worker.py
"""Scanner Worker: Background process monitoring Nifty 50 constituents.

Can run single-shot or scheduled every N minutes to identify:
1. Confluence breakouts
2. Volume expansion spikes (> 1.25x)
3. Candlestick reversal patterns
"""
import asyncio
import sys
from datetime import datetime
from ..domain.config import Settings
from ..domain.enums import Timeframe
from ..core.scanner import ScannerService, NIFTY_LIQUID_UNIVERSE
from ..wiring.container import Container

# Windows UTF-8 console output
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


async def run_scanner_cycle(container: Container, timeframe: str = "15m", min_score: float = 20.0) -> list:
    """Execute a single scan across liquid symbols."""
    scanner = ScannerService(data_port=container.data_port)
    tf = Timeframe(timeframe)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Starting Scan on {len(NIFTY_LIQUID_UNIVERSE)} Nifty constituents ({timeframe})...")
    
    opportunities = await scanner.scan_universe(symbols=NIFTY_LIQUID_UNIVERSE, timeframe=tf, min_opportunity_score=min_score)
    
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Scan Complete. Found {len(opportunities)} qualified setups:\n")
    print(f"{'SYMBOL':<15} {'SPOT (INR)':<12} {'REGIME':<20} {'BIAS':<8} {'SCORE':<8} {'VOL RATIO':<10} {'TRIGGER'}")
    print("-" * 105)
    for opp in opportunities:
        print(f"{opp.symbol:<15} {opp.spot_price:<12.2f} {opp.regime.value:<20} {opp.bias.value:<8} {opp.opportunity_score:<8.1f} {opp.volume_ratio:<10.2f} {opp.trigger_reason[:30]}")
    print("-" * 105)
    return opportunities


async def main():
    settings = Settings.load()
    use_mock = "--mock" in sys.argv
    tf = "15m"
    for arg in sys.argv:
        if arg.startswith("--tf="):
            tf = arg.split("=")[1]

    container = Container(settings=settings, use_mock=use_mock)
    await run_scanner_cycle(container, timeframe=tf, min_score=20.0)


if __name__ == "__main__":
    asyncio.run(main())

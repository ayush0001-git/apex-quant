# apex-quant/src/apex/core/scanner.py
"""Market Scanner Service: Multi-asset technical screening across Indian equities.

Scans universes (Nifty 50 / F&O) and ranks candidates by:
1. Technical Confluence Score
2. Volume Expansion Ratio (> 1.15x)
3. Non-repainting Candlestick Pattern Detection
4. Momentum & Regime Alignment
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence, List, Mapping, Any
from ..domain.enums import Direction, MarketRegime, Timeframe
from ..domain.models import Bar, FeatureSnapshot
from ..ports.data_port import MarketDataPort
from .features import FeatureService
from .ingestion import IngestionService


# Standard high-liquidity NSE universe
NIFTY_LIQUID_UNIVERSE = [
    "RELIANCE.NS",
    "TCS.NS",
    "HDFCBANK.NS",
    "INFY.NS",
    "ICICIBANK.NS",
    "BHARTIARTL.NS",
    "SBIN.NS",
    "ITC.NS",
    "KOTAKBANK.NS",
    "LT.NS",
    "AXISBANK.NS",
    "BAJFINANCE.NS",
    "MARUTI.NS",
    "TATAMOTORS.NS",
    "SUNPHARMA.NS",
    "TITAN.NS",
    "M&M.NS",
    "WIPRO.NS",
    "NTPC.NS",
    "POWERGRID.NS",
]


@dataclass(frozen=True)
class ScanOpportunity:
    """A detected actionable setup from the scanner."""
    symbol: str
    timestamp: datetime
    spot_price: float
    regime: MarketRegime
    confluence_score: float
    volume_ratio: float
    patterns: tuple[str, ...]
    bias: Direction
    opportunity_score: float
    potential_entry: float
    potential_stop: float
    potential_target: float
    trigger_reason: str


class ScannerService:
    """Stateless screening engine that evaluates multiple assets."""

    def __init__(self, data_port: MarketDataPort) -> None:
        self._data_port = data_port
        self._ingestion = IngestionService()
        self._features = FeatureService()

    async def scan_symbol(
        self,
        symbol: str,
        timeframe: Timeframe = Timeframe.M15,
        bars_count: int = 50,
    ) -> ScanOpportunity | None:
        """Scan a single symbol and return opportunity details."""
        try:
            raw_bars = await self._data_port.get_ohlcv(symbol, timeframe, bars_count)
            validated_bars = self._ingestion.validate_and_normalize(raw_bars)
            snapshot = self._features.compute(validated_bars)

            # Determine bias and setup criteria
            bias = Direction.HOLD
            reasons = []

            # Bullish Criteria: Confluence, Trend, Patterns
            if snapshot.regime == MarketRegime.BULL_EXPANSION and snapshot.confluence_score >= 50.0:
                bias = Direction.LONG
                reasons.append(f"Bullish Trend (Confluence {snapshot.confluence_score:.1f})")
            elif snapshot.regime == MarketRegime.BEAR_EXPANSION and snapshot.confluence_score <= 50.0:
                bias = Direction.SHORT
                reasons.append(f"Bearish Trend (Confluence {snapshot.confluence_score:.1f})")

            # Pattern boosters
            bull_patterns = {"Hammer", "Bullish Engulfing", "Morning Star"}
            bear_patterns = {"Shooting Star", "Bearish Engulfing", "Evening Star"}

            active_bull_patterns = [p for p in snapshot.patterns if p in bull_patterns]
            active_bear_patterns = [p for p in snapshot.patterns if p in bear_patterns]

            if active_bull_patterns and bias != Direction.SHORT:
                bias = Direction.LONG
                reasons.append(f"Bullish Pattern: {', '.join(active_bull_patterns)}")
            elif active_bear_patterns and bias != Direction.LONG:
                bias = Direction.SHORT
                reasons.append(f"Bearish Pattern: {', '.join(active_bear_patterns)}")

            if snapshot.volume_ratio > 1.25:
                reasons.append(f"Volume Surge ({snapshot.volume_ratio:.2f}x)")

            atr = snapshot.indicators.get("atr_14", snapshot.spot_price * 0.01)
            spot = snapshot.spot_price

            if bias == Direction.LONG:
                entry = spot
                stop = round(spot - (1.5 * atr), 2)
                target = round(spot + (3.0 * atr), 2)
                # Opportunity score: 0 to 100
                score = round((snapshot.confluence_score * 0.5) + (min(snapshot.volume_ratio, 2.0) * 20), 1)
                if active_bull_patterns:
                    score = min(100.0, score + 15.0)
            elif bias == Direction.SHORT:
                entry = spot
                stop = round(spot + (1.5 * atr), 2)
                target = round(spot - (3.0 * atr), 2)
                score = round(((100.0 - snapshot.confluence_score) * 0.5) + (min(snapshot.volume_ratio, 2.0) * 20), 1)
                if active_bear_patterns:
                    score = min(100.0, score + 15.0)
            else:
                entry = spot
                stop = round(spot - atr, 2)
                target = round(spot + atr, 2)
                score = round(snapshot.confluence_score * 0.4, 1)

            trigger = "; ".join(reasons) if reasons else "Range Compression / Routine Observation"

            return ScanOpportunity(
                symbol=symbol,
                timestamp=snapshot.timestamp,
                spot_price=spot,
                regime=snapshot.regime,
                confluence_score=snapshot.confluence_score,
                volume_ratio=snapshot.volume_ratio,
                patterns=snapshot.patterns,
                bias=bias,
                opportunity_score=score,
                potential_entry=entry,
                potential_stop=stop,
                potential_target=target,
                trigger_reason=trigger,
            )
        except Exception:
            return None

    async def scan_universe(
        self,
        symbols: Sequence[str] | None = None,
        timeframe: Timeframe = Timeframe.M15,
        min_opportunity_score: float = 20.0,
    ) -> List[ScanOpportunity]:
        """Scan a universe of symbols and return ranked opportunities."""
        target_symbols = symbols or NIFTY_LIQUID_UNIVERSE
        results: List[ScanOpportunity] = []

        for sym in target_symbols:
            opp = await self.scan_symbol(sym, timeframe=timeframe)
            if opp is not None and opp.opportunity_score >= min_opportunity_score:
                results.append(opp)

        results.sort(key=lambda x: x.opportunity_score, reverse=True)
        return results

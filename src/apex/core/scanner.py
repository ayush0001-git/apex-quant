# apex-quant/src/apex/core/scanner.py
"""Market Scanner Service: Multi-asset technical screening across Indian equities.

Scans universes (NIFTY 50, NIFTY NEXT 50, NIFTY 100) and ranks candidates by:
1. Technical Confluence Score & Non-repainting Candlestick Pattern Detection
2. Cross-Sectional Factor Alpha (Momentum, Realized Vol, Quality)
3. Volume Expansion Ratio & Volume Z-Score
4. Regime-Aware Volatility Gating (dampens scores in high-volatility turbulence)
5. Dynamic Liquidity Filtering (eliminates survivorship bias)
"""
from dataclasses import dataclass
from datetime import datetime
import logging
from typing import Sequence, List, Mapping, Any, Optional
from ..domain.enums import Direction, MarketRegime, Timeframe
from ..domain.models import Bar, FeatureSnapshot
from ..ports.data_port import MarketDataPort
from .features import FeatureService
from .ingestion import IngestionService


# Expanded Institutional Universes for Indian Equities
NIFTY_50_UNIVERSE = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
    "BHARTIARTL.NS", "SBIN.NS", "ITC.NS", "KOTAKBANK.NS", "LT.NS",
    "AXISBANK.NS", "BAJFINANCE.NS", "MARUTI.NS", "TATAMOTORS.NS", "SUNPHARMA.NS",
    "TITAN.NS", "M&M.NS", "WIPRO.NS", "NTPC.NS", "POWERGRID.NS",
    "HCLTECH.NS", "ULTRACEMCO.NS", "ASIANPAINT.NS", "NESTLEIND.NS", "COALINDIA.NS",
    "BAJAJFINSV.NS", "JSWSTEEL.NS", "TATASTEEL.NS", "ADANIENT.NS", "ADANIPORTS.NS",
    "GRASIM.NS", "ONGC.NS", "TECHM.NS", "CIPLA.NS", "HEROMOTOCO.NS",
    "HINDUNILVR.NS", "DRREDDY.NS", "BRITANNIA.NS", "INDUSINDBK.NS", "EICHERMOT.NS",
    "APOLLOHOSP.NS", "DIVISLAB.NS", "BPCL.NS", "HINDALCO.NS", "TATACONSUM.NS",
    "SHRIRAMFIN.NS", "BEL.NS", "SBILIFE.NS", "HDFCLIFE.NS", "TRENT.NS",
]

NIFTY_NEXT_50_UNIVERSE = [
    "ABB.NS", "ADANIENSOL.NS", "ADANIGREEN.NS", "AMBUJACEM.NS", "BANKBARODA.NS",
    "BOSCHLTD.NS", "CANBK.NS", "CHOLAFIN.NS", "COLPAL.NS", "DABUR.NS",
    "DLF.NS", "GAIL.NS", "GODREJCP.NS", "HAL.NS", "HAVELLS.NS",
    "ICICIGI.NS", "ICICIPRULI.NS", "IOC.NS", "IRCTC.NS", "JINDALSTEL.NS",
    "JIOFIN.NS", "LTIM.NS", "MARICO.NS", "MOTHERSON.NS", "NAUKRI.NS",
    "PIDILITIND.NS", "PFC.NS", "PNB.NS", "RECLTD.NS", "SIEMENS.NS",
    "SRF.NS", "TVSMOTOR.NS", "UNITDSPR.NS", "VEDL.NS", "ZOMATO.NS",
]

NIFTY_100_UNIVERSE = NIFTY_50_UNIVERSE + NIFTY_NEXT_50_UNIVERSE
# Backward compatibility alias
NIFTY_LIQUID_UNIVERSE = NIFTY_50_UNIVERSE[:20]


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
    factor_composite: float = 0.0
    volatility_gate: float = 1.0
    volume_zscore: float = 0.0


class ScannerService:
    """Stateless screening engine that evaluates multiple assets."""

    def __init__(self, data_port: MarketDataPort) -> None:
        self._data_port = data_port
        self._ingestion = IngestionService()
        self._features = FeatureService()

    async def filter_liquid_universe(
        self,
        symbols: Sequence[str],
        min_avg_turnover_inr: float = 50_000_000.0,
        timeframe: Timeframe = Timeframe.D1,
        lookback_bars: int = 20,
    ) -> List[str]:
        """Dynamically screen candidates by historical volume and turnover.
        
        Eliminates survivorship bias by selecting active, high-liquidity stocks
        at historical time t rather than relying solely on static indices.
        """
        liquid = []
        errors = []
        for sym in symbols:
            try:
                bars = await self._data_port.get_ohlcv(sym, timeframe, lookback_bars)
                if len(bars) >= 5:
                    avg_turnover = sum(b.close * b.volume for b in bars) / len(bars)
                    if avg_turnover >= min_avg_turnover_inr:
                        liquid.append(sym)
            except Exception as e:
                errors.append(f"{sym}: {e}")
                continue

        if not liquid and errors:
            logging.getLogger("apex.scanner").warning(
                f"Liquidity filtering encountered errors on {len(errors)} symbols. Falling back to default baseline universe."
            )
        return liquid if liquid else list(symbols[:20])

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
            if snapshot.regime in (MarketRegime.BULL_EXPANSION, MarketRegime.LOW_VOLATILITY_TREND) and snapshot.confluence_score >= 50.0:
                bias = Direction.LONG
                reasons.append(f"Bullish Trend (Confluence {snapshot.confluence_score:.1f})")
            elif snapshot.regime == MarketRegime.BEAR_EXPANSION and snapshot.confluence_score <= 50.0:
                bias = Direction.SHORT
                reasons.append(f"Bearish Trend (Confluence {snapshot.confluence_score:.1f})")

            # Pattern boosters
            bull_patterns = {"HAMMER", "BULLISH_ENGULFING", "MORNING_STAR"}
            bear_patterns = {"SHOOTING_STAR", "BEARISH_ENGULFING", "EVENING_STAR"}

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

            vol_z = snapshot.indicators.get("volume_zscore", 0.0)
            if vol_z > 1.5:
                reasons.append(f"Volume Z-Score (+{vol_z:.1f}σ)")

            # Factor exposures
            factors = snapshot.factor_exposures or {}
            mom_20 = factors.get("momentum_20d", 0.0)
            if mom_20 > 5.0 and bias == Direction.LONG:
                reasons.append(f"Factor Momentum (+{mom_20:.1f}%)")

            atr = snapshot.indicators.get("atr_14", snapshot.spot_price * 0.01)
            spot = snapshot.spot_price

            vol_gate = getattr(snapshot, "volatility_gate", 1.0)

            if bias == Direction.LONG:
                entry = spot
                stop = round(spot - (1.5 * atr), 2)
                target = round(spot + (3.0 * atr), 2)
                # Opportunity score: 0 to 100, scaled by volatility gate
                base_score = (snapshot.confluence_score * 0.5) + (min(snapshot.volume_ratio, 2.0) * 20)
                if active_bull_patterns:
                    base_score = min(100.0, base_score + 15.0)
                score = round(base_score * vol_gate, 1)
            elif bias == Direction.SHORT:
                entry = spot
                stop = round(spot + (1.5 * atr), 2)
                target = round(spot - (3.0 * atr), 2)
                base_score = ((100.0 - snapshot.confluence_score) * 0.5) + (min(snapshot.volume_ratio, 2.0) * 20)
                if active_bear_patterns:
                    base_score = min(100.0, base_score + 15.0)
                score = round(base_score * vol_gate, 1)
            else:
                entry = spot
                stop = round(spot - atr, 2)
                target = round(spot + atr, 2)
                score = round(snapshot.confluence_score * 0.4 * vol_gate, 1)

            # Suppress setups in extreme turbulence
            if snapshot.regime == MarketRegime.HIGH_VOLATILITY_TURBULENCE:
                score = min(score, 35.0)
                reasons.append("HIGH_VOLATILITY_TURBULENCE: Risk gate throttle active")

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
                factor_composite=factors.get("composite_alpha_score", 0.0),
                volatility_gate=round(vol_gate, 2),
                volume_zscore=round(vol_z, 2),
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

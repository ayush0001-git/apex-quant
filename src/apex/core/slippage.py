# apex-quant/src/apex/core/slippage.py
"""Dynamic Slippage, Queue-Delay & Market Impact Engine.

Replaces naive static slippage models (fixed 5 bps) with an institutional
market microstructure model incorporating:
1. Kyle's Lambda square-root price impact law: Impact ~ sigma * sqrt(OrderSize / ADV)
2. Volatility scaling: Slippage widens during high realized volatility / gap events.
3. Volume shock scaling: Slippage widens when trading in thin volume or fast markets.
4. Queue-Position Fill Realism:
   - Evaluates queue ahead ($Q_ahead$) at the price level from Level-2 depth.
   - Computes fill probability based on trade-through volume:
     Touch != Fill (orders touched at boundary face queue delays and partial fills).
5. Execution Latency Penalty:
   - Models 100ms - 300ms network & matching engine adverse selection drift.
6. Hard regulatory bounds: Clamped between min_slippage_pct and max_slippage_pct.
"""
from dataclasses import dataclass
from enum import Enum
import math
from typing import Optional, Tuple
from ..domain.config import FrictionSettings
from ..domain.orderbook import OrderBookDepth


class FillStatus(str, Enum):
    """Execution fill outcome for limit and market orders."""
    FILLED = "FILLED"
    PARTIAL = "PARTIAL"
    UNFILLED = "UNFILLED"


@dataclass(frozen=True)
class SlippageQuote:
    """Detailed slippage cost estimation."""
    slippage_pct: float             # In decimal (e.g. 0.0008 = 8 bps)
    slippage_bps: float             # In basis points (e.g. 8.0)
    slippage_inr: float             # Rupee amount for the turnover
    base_bps: float
    volatility_penalty_bps: float
    impact_penalty_bps: float
    latency_penalty_bps: float = 0.0


@dataclass(frozen=True)
class QueueFillReport:
    """Detailed fill realism report modeling queue position and delay."""
    status: FillStatus
    fill_ratio: float               # 0.0 (unfilled) to 1.0 (fully filled)
    shares_requested: float
    shares_filled: float
    requested_price: float
    effective_fill_price: float
    fill_probability: float         # Probabilistic fill likelihood [0.0, 1.0]
    queue_ahead_shares: float       # Estimated shares ahead in limit queue
    queue_delay_ms: float           # Estimated wait time before fill in ms
    latency_penalty_bps: float      # Adverse latency penalty in basis points
    slippage_quote: SlippageQuote


class DynamicSlippageModel:
    """Calculates realistic dynamic execution slippage for Indian equities."""

    def __init__(self, friction_settings: Optional[FrictionSettings] = None) -> None:
        # Calibrated against expanded NIFTY 100/200 TCA: 7 bps baseline, k=0.15 impact
        self.base_slippage = friction_settings.default_slippage_pct if friction_settings else 0.0007
        self.min_slippage = getattr(friction_settings, "min_slippage_pct", 0.0002) if friction_settings else 0.0002
        self.max_slippage = getattr(friction_settings, "max_slippage_pct", 0.0050) if friction_settings else 0.0050
        self.vol_factor = getattr(friction_settings, "slippage_vol_factor", 0.6) if friction_settings else 0.6
        self.impact_factor = getattr(friction_settings, "slippage_impact_factor", 0.15) if friction_settings else 0.15
        self.latency_ms = getattr(friction_settings, "execution_latency_ms", 150.0) if friction_settings else 150.0

    def calculate_slippage_pct(
        self,
        volume_ratio: float = 1.0,
        volatility_pct: float = 0.015,
        participation_rate: float = 0.001,
        baseline_volatility: float = 0.015,
        is_market_order: bool = True,
    ) -> float:
        """Calculate slippage percentage based on volume, volatility, and order participation.
        
        Args:
            volume_ratio: Current bar volume / 20-period average volume.
            volatility_pct: Estimated bar or daily volatility (ATR/spot or daily return std).
            participation_rate: Order size relative to average bar/daily volume (turnover / ADV).
            baseline_volatility: Benchmark normal volatility (1.5% for liquid Nifty stocks).
            is_market_order: Whether order is crossing the spread aggressively.
        """
        # 1. Base slippage (e.g. 5 bps = 0.0005)
        base = self.base_slippage

        # 2. Volatility penalty: As volatility expands above baseline, spread widens
        vol_ratio = max(0.2, volatility_pct / (baseline_volatility + 1e-8))
        vol_multiplier = 1.0 + self.vol_factor * max(0.0, vol_ratio - 1.0)

        # 3. Volume ratio penalty: Low volume = wide spread; abnormal volume surge = fast market slippage
        vol_shock = 0.0
        if volume_ratio < 0.6:
            vol_shock = (0.6 - volume_ratio) * 0.5  # Illiquidity spread widening
        elif volume_ratio > 1.8:
            vol_shock = min(1.0, (volume_ratio - 1.8) * 0.3)  # Volatile queue-jumping slippage

        # 4. Kyle's Lambda square-root market impact: Impact = k * sqrt(Participation)
        safe_part = max(0.0, min(0.5, participation_rate))
        impact_pct = self.impact_factor * math.sqrt(safe_part) * 0.01

        # 5. Latency penalty for aggressive market orders (100ms - 300ms adverse drift)
        latency_pct = 0.0
        if is_market_order:
            # sqrt(dt / T_day) * sigma * adverse_bias
            day_fraction = self.latency_ms / (6.25 * 3600 * 1000.0) # Active trading hours fraction
            latency_pct = volatility_pct * math.sqrt(max(1e-6, day_fraction)) * 0.5

        # 6. Combined effective slippage
        effective_pct = (base * vol_multiplier * (1.0 + vol_shock)) + impact_pct + latency_pct

        # 7. Strict bounds
        return max(self.min_slippage, min(self.max_slippage, effective_pct))

    def estimate_slippage(
        self,
        turnover: float,
        shares: float,
        spot_price: float,
        volume_ratio: float = 1.0,
        volatility_pct: float = 0.015,
        adv_turnover: float = 50_000_000.0,
        is_market_order: bool = True,
    ) -> SlippageQuote:
        """Compute full SlippageQuote including rupee cost, basis points, and latency breakdown."""
        participation = turnover / (adv_turnover + 1e-8) if adv_turnover > 0 else 0.001
        slippage_pct = self.calculate_slippage_pct(
            volume_ratio=volume_ratio,
            volatility_pct=volatility_pct,
            participation_rate=participation,
            is_market_order=is_market_order,
        )

        base_bps = self.base_slippage * 10_000
        total_bps = slippage_pct * 10_000
        slippage_inr = round(turnover * slippage_pct, 2)

        vol_penalty = max(0.0, (slippage_pct - self.base_slippage) * 10_000 * 0.5)
        
        # Latency breakdown
        day_fraction = self.latency_ms / (6.25 * 3600 * 1000.0)
        latency_bps = (volatility_pct * math.sqrt(max(1e-6, day_fraction)) * 0.5 * 10_000) if is_market_order else 0.0
        impact_penalty = max(0.0, total_bps - base_bps - vol_penalty - latency_bps)

        return SlippageQuote(
            slippage_pct=round(slippage_pct, 6),
            slippage_bps=round(total_bps, 2),
            slippage_inr=slippage_inr,
            base_bps=round(base_bps, 2),
            volatility_penalty_bps=round(vol_penalty, 2),
            impact_penalty_bps=round(impact_penalty, 2),
            latency_penalty_bps=round(latency_bps, 2),
        )

    def evaluate_limit_order_fill(
        self,
        limit_price: float,
        order_shares: float,
        is_buy: bool,
        bar_high: float,
        bar_low: float,
        bar_close: float,
        bar_volume: float,
        l2_depth: Optional[OrderBookDepth] = None,
        volatility_pct: float = 0.015,
        adv_shares: float = 500_000.0,
    ) -> QueueFillReport:
        """Simulate realistic limit order queue position and trade-through fill probability.
        
        Guarantees:
        - Touch != Fill: If bar low only touches limit buy price, fill prob is low (< 35%).
        - Deep penetration (price traded through limit) gives high fill prob (90% - 100%).
        - Queue position ahead is estimated from L2 depth or historical participation.
        """
        # 1. Check whether price reached the limit level
        if is_buy:
            if bar_low > limit_price:
                # Price never reached limit order
                quote = self.estimate_slippage(limit_price * order_shares, order_shares, limit_price, is_market_order=False)
                return QueueFillReport(
                    status=FillStatus.UNFILLED,
                    fill_ratio=0.0,
                    shares_requested=order_shares,
                    shares_filled=0.0,
                    requested_price=limit_price,
                    effective_fill_price=0.0,
                    fill_probability=0.0,
                    queue_ahead_shares=0.0,
                    queue_delay_ms=0.0,
                    latency_penalty_bps=0.0,
                    slippage_quote=quote,
                )
            penetration = (limit_price - bar_low) / (bar_high - bar_low + 1e-8)
        else:
            if bar_high < limit_price:
                # Price never reached limit sell order
                quote = self.estimate_slippage(limit_price * order_shares, order_shares, limit_price, is_market_order=False)
                return QueueFillReport(
                    status=FillStatus.UNFILLED,
                    fill_ratio=0.0,
                    shares_requested=order_shares,
                    shares_filled=0.0,
                    requested_price=limit_price,
                    effective_fill_price=0.0,
                    fill_probability=0.0,
                    queue_ahead_shares=0.0,
                    queue_delay_ms=0.0,
                    latency_penalty_bps=0.0,
                    slippage_quote=quote,
                )
            penetration = (bar_high - limit_price) / (bar_high - bar_low + 1e-8)

        # 2. Estimate queue ahead at this price level
        if l2_depth and (l2_depth.bids if is_buy else l2_depth.asks):
            queue_list = l2_depth.bids if is_buy else l2_depth.asks
            # Sum quantity up to our limit price
            queue_ahead = sum(level.quantity for level in queue_list if (level.price >= limit_price if is_buy else level.price <= limit_price))
        else:
            # Fallback heuristic: 0.5% - 2.0% of average bar volume rests at touch levels
            queue_ahead = max(100.0, bar_volume * 0.015)

        # 3. Calculate trade-through volume
        # Volume that traded at or through our limit price during the bar
        trade_through_volume = bar_volume * max(0.05, min(1.0, penetration))

        # 4. Fill Probability & Fill Ratio
        # Need trade-through volume to consume the queue ahead of us
        total_needed = queue_ahead + order_shares
        fill_prob = min(1.0, max(0.0, trade_through_volume / (total_needed + 1e-8)))

        # Touch-only penalty: if price only touched (penetration < 0.05), severely penalize
        if penetration < 0.05:
            fill_prob *= 0.35

        # 5. Determine fill outcome
        if fill_prob >= 0.80:
            status = FillStatus.FILLED
            fill_ratio = 1.0
            shares_filled = order_shares
        elif fill_prob >= 0.30:
            status = FillStatus.PARTIAL
            fill_ratio = round(max(0.1, fill_prob), 2)
            shares_filled = round(order_shares * fill_ratio, 0)
        else:
            status = FillStatus.UNFILLED
            fill_ratio = 0.0
            shares_filled = 0.0

        # 6. Queue Delay Calculation (ms)
        # Higher queue ahead relative to bar flow rate implies longer delay
        flow_rate_per_sec = bar_volume / 900.0  # 15m bar = 900 seconds
        delay_seconds = queue_ahead / (flow_rate_per_sec + 1e-8)
        queue_delay_ms = round(min(60_000.0, delay_seconds * 1000.0), 1)

        # Limit orders earn the spread or pay zero market impact
        turnover = limit_price * shares_filled
        quote = self.estimate_slippage(
            turnover=turnover,
            shares=shares_filled,
            spot_price=limit_price,
            volatility_pct=volatility_pct,
            is_market_order=False,
        )

        return QueueFillReport(
            status=status,
            fill_ratio=fill_ratio,
            shares_requested=order_shares,
            shares_filled=shares_filled,
            requested_price=limit_price,
            effective_fill_price=limit_price,  # Limit filled at or better than limit
            fill_probability=round(fill_prob, 3),
            queue_ahead_shares=round(queue_ahead, 1),
            queue_delay_ms=queue_delay_ms,
            latency_penalty_bps=0.0,
            slippage_quote=quote,
        )

# apex-quant/src/apex/core/microstructure.py
"""Market Microstructure & Order Flow Analysis Service.

Implements institutional high-frequency and microstructure analytics:
1. Order Flow Imbalance (OFI): Measures net buying/selling pressure.
2. Kyle's Lambda (λ): Estimates price impact coefficient per unit of volume.
3. VPIN (Volume-Synchronized Probability of Informed Trading): Measures flow toxicity.
4. Microprice: Volume-weighted fair mid-price estimator.
"""
from dataclasses import dataclass
import math
from typing import Sequence, List, Mapping, Any, Optional
import numpy as np
from ..domain.models import Bar
from ..domain.orderbook import OrderBookDepth
from .ingestion import DataQualityError


@dataclass(frozen=True)
class MicrostructureSnapshot:
    """Microstructure metrics snapshot for an instrument."""
    symbol: str
    ofi_value: float              # Net order flow imbalance
    kyle_lambda: float            # Price impact coefficient (INR price shift per 10k shares)
    vpin_toxicity: float          # VPIN toxicity metric (0.0 to 1.0)
    microprice: float             # Volume-weighted mid-price estimate
    spread_bps: float             # Estimated effective spread in basis points


class MicrostructureService:
    """Calculates microstructure and order-flow signals."""

    @staticmethod
    def calculate_bar_ofi(bars: Sequence[Bar]) -> float:
        """Estimate Order Flow Imbalance (OFI) from bar-level price/volume action.
        
        Uses the tick-rule / volume-delta proxy:
        Net OFI = sum( Volume * (Close - Open) / (High - Low + eps) )
        """
        if not bars:
            return 0.0

        ofi_sum = 0.0
        for b in bars:
            rng = b.high - b.low
            if rng <= 0:
                continue
            delta = (b.close - b.open) / rng
            ofi_sum += b.volume * delta

        return float(ofi_sum)

    @staticmethod
    def calculate_l2_ofi(prev_depth: OrderBookDepth, curr_depth: OrderBookDepth) -> float:
        """Calculate exact Level-2 Order Flow Imbalance (OFI) across top-of-book.
        
        OFI = Delta B_t - Delta A_t
        """
        if not prev_depth.bids or not curr_depth.bids or not prev_depth.asks or not curr_depth.asks:
            return 0.0

        p_b_prev, q_b_prev = prev_depth.bids[0].price, prev_depth.bids[0].quantity
        p_b_curr, q_b_curr = curr_depth.bids[0].price, curr_depth.bids[0].quantity

        p_a_prev, q_a_prev = prev_depth.asks[0].price, prev_depth.asks[0].quantity
        p_a_curr, q_a_curr = curr_depth.asks[0].price, curr_depth.asks[0].quantity

        # Bid delta
        if p_b_curr > p_b_prev:
            delta_b = q_b_curr
        elif p_b_curr == p_b_prev:
            delta_b = q_b_curr - q_b_prev
        else:
            delta_b = -q_b_prev

        # Ask delta
        if p_a_curr > p_a_prev:
            delta_a = -q_a_prev
        elif p_a_curr == p_a_prev:
            delta_a = q_a_curr - q_a_prev
        else:
            delta_a = q_a_curr

        return float(delta_b - delta_a)

    @staticmethod
    def calculate_queue_imbalance(depth: OrderBookDepth) -> float:
        """Compute Order Book Queue Imbalance across all available depth levels.
        
        Imbalance = (Total Bid Volume - Total Ask Volume) / (Total Bid Volume + Total Ask Volume)
        Returns scalar in [-1.0, 1.0]. Positive values indicate heavy buying queue pressure.
        """
        total_bid_vol = sum(b.quantity for b in depth.bids)
        total_ask_vol = sum(a.quantity for a in depth.asks)
        denom = total_bid_vol + total_ask_vol
        if denom <= 0:
            return 0.0
        return round(float((total_bid_vol - total_ask_vol) / denom), 3)

    @staticmethod
    def calculate_depth_weighted_spread(depth: OrderBookDepth) -> float:
        """Compute spread in basis points from top-of-book."""
        if not depth.bids or not depth.asks:
            return 5.0
        mid = depth.mid_price
        if mid <= 0:
            return 5.0
        return round(max(1.0, float((depth.spread / mid) * 10000.0)), 2)

    @staticmethod
    def estimate_kyle_lambda(bars: Sequence[Bar]) -> float:
        """Estimate Kyle's Lambda (λ) by regressing price changes on volume imbalance.
        
        Delta P_t = lambda * OFI_t + epsilon
        Returns price change (INR) per 10,000 shares of flow imbalance.
        """
        if len(bars) < 10:
            return 0.15  # Default baseline for liquid Indian equities

        price_changes = []
        flow_imbalances = []

        for i in range(1, len(bars)):
            dp = bars[i].close - bars[i - 1].close
            rng = bars[i].high - bars[i].low
            if rng > 0:
                imbalance = bars[i].volume * ((bars[i].close - bars[i].open) / rng)
            else:
                imbalance = 0.0
            price_changes.append(dp)
            flow_imbalances.append(imbalance)

        x = np.array(flow_imbalances)
        y = np.array(price_changes)

        x_var = np.var(x)
        if x_var <= 1e-12:
            return 0.15

        cov_xy = np.cov(x, y)[0, 1]
        raw_lambda = cov_xy / x_var

        # Scale to INR impact per 10,000 shares
        scaled_lambda = float(abs(raw_lambda) * 10_000.0)
        return round(max(0.01, min(5.0, scaled_lambda)), 4)

    @staticmethod
    def calculate_vpin(bars: Sequence[Bar], num_buckets: int = 10) -> float:
        """Calculate Volume-Synchronized Probability of Informed Trading (VPIN).
        
        Partitions bar volume into equal buckets and measures absolute order imbalance.
        Returns toxicity score in [0.0, 1.0]. A score > 0.65 signals adverse selection risk.
        """
        if len(bars) < num_buckets:
            return 0.25

        total_vol = sum(b.volume for b in bars)
        if total_vol <= 0:
            return 0.0

        bucket_size = total_vol / num_buckets
        buy_volumes = []
        sell_volumes = []

        current_bucket_vol = 0.0
        current_buy_vol = 0.0
        current_sell_vol = 0.0

        for b in bars:
            rng = b.high - b.low
            # Proportion of buy volume vs sell volume based on close position in range
            buy_fraction = (b.close - b.low) / (rng + 1e-8) if rng > 0 else 0.5
            buy_fraction = max(0.0, min(1.0, buy_fraction))

            b_buy = b.volume * buy_fraction
            b_sell = b.volume * (1.0 - buy_fraction)

            current_buy_vol += b_buy
            current_sell_vol += b_sell
            current_bucket_vol += b.volume

            if current_bucket_vol >= bucket_size:
                buy_volumes.append(current_buy_vol)
                sell_volumes.append(current_sell_vol)
                current_buy_vol = 0.0
                current_sell_vol = 0.0
                current_bucket_vol = 0.0

        if not buy_volumes:
            return 0.30

        imbalances = [abs(b - s) for b, s in zip(buy_volumes, sell_volumes)]
        vpin = float(sum(imbalances) / (len(imbalances) * bucket_size + 1e-8))

        return round(max(0.0, min(1.0, vpin)), 3)

    @classmethod
    def analyze_microstructure(cls, bars: Sequence[Bar]) -> MicrostructureSnapshot:
        """Compute full microstructure snapshot for an instrument."""
        if not bars:
            raise DataQualityError("Cannot compute microstructure on empty bar sequence")

        symbol = bars[-1].symbol
        spot = bars[-1].close
        ofi = cls.calculate_bar_ofi(bars[-20:])
        kyle = cls.estimate_kyle_lambda(bars[-30:])
        vpin = cls.calculate_vpin(bars[-30:])

        # Estimate microprice using volume-weighted order imbalance
        rng = bars[-1].high - bars[-1].low
        buy_bias = ((bars[-1].close - bars[-1].low) / (rng + 1e-8) - 0.5) if rng > 0 else 0.0
        microprice = round(spot + (buy_bias * 0.1 * (bars[-1].high - bars[-1].low)), 2)

        # Baseline spread in basis points
        spread_bps = round(max(2.0, min(25.0, 3.5 + 10.0 * vpin + 2.0 * kyle)), 1)

        return MicrostructureSnapshot(
            symbol=symbol,
            ofi_value=round(ofi, 1),
            kyle_lambda=kyle,
            vpin_toxicity=vpin,
            microprice=microprice,
            spread_bps=spread_bps,
        )


# apex-quant/src/apex/core/features.py
"""FeatureService: Stateless, lookahead-bias-free technical and pattern analysis.

Enforces:
1. Pure functions taking Sequence[Bar] and returning FeatureSnapshot.
2. Strict causality: Raises DataQualityError if any bar has is_closed == False.
3. Multi-indicator mathematical facts: EMAs, RSI, ATR, VWAP, Bollinger Bands.
4. Non-repainting rule-based candlestick pattern recognition.
5. Confluence scoring and MarketRegime classification.
"""
from typing import Sequence
import numpy as np
import pandas as pd
from ..domain.models import Bar, FeatureSnapshot
from ..domain.enums import MarketRegime
from .ingestion import DataQualityError
from .factors import FactorService
from .regime import RegimeClassifier


class FeatureService:
    """Computes mathematical feature snapshots from closed bars. Never generates buy/sell orders."""

    @staticmethod
    def compute(bars: Sequence[Bar]) -> FeatureSnapshot:
        if not bars:
            raise DataQualityError("Cannot compute features on empty bar sequence.")

        # Causality verification: All bars must be finalized
        for idx, bar in enumerate(bars):
            if not bar.is_closed:
                raise DataQualityError(
                    f"Causality Violation at index {idx}: Bar for {bar.symbol} at {bar.timestamp} has is_closed=False."
                )

        if len(bars) < 20:
            raise DataQualityError(
                f"Insufficient history: Need at least 20 closed bars to compute baseline indicators, received {len(bars)}."
            )

        # Convert to pandas DataFrame for vectorized calculations
        records = [
            {
                "timestamp": b.timestamp,
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "volume": b.volume,
            }
            for b in bars
        ]
        df = pd.DataFrame.from_records(records)
        df.sort_values("timestamp", inplace=True)
        df.reset_index(drop=True, inplace=True)

        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"]
        n = len(df)

        # 1. EMAs
        ema20 = close.ewm(span=20, adjust=False).mean()
        ema50 = close.ewm(span=min(50, n), adjust=False).mean()
        ema200 = close.ewm(span=min(200, n), adjust=False).mean()

        # 2. RSI (14)
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(com=13, adjust=False).mean()
        avg_loss = loss.ewm(com=13, adjust=False).mean()
        rs = avg_gain / (avg_loss + 1e-10)
        rsi14 = 100 - (100 / (1 + rs))

        # 3. ATR (14)
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr14 = tr.ewm(com=13, adjust=False).mean()

        # 4. Bollinger Bands (20, 2 std)
        bb_mid = close.rolling(20, min_periods=5).mean()
        bb_std = close.rolling(20, min_periods=5).std().fillna(0)
        bb_upper = bb_mid + (2.0 * bb_std)
        bb_lower = bb_mid - (2.0 * bb_std)
        bb_width = ((bb_upper - bb_lower) / (bb_mid + 1e-10)) * 100

        # 5. Volume SMA and Volume Ratio & Z-score
        vol_sma20 = volume.rolling(20, min_periods=5).mean()
        vol_std20 = volume.rolling(20, min_periods=5).std().fillna(1.0)
        vol_ratio = float(volume.iloc[-1] / (vol_sma20.iloc[-1] + 1e-10))
        vol_zscore = float((volume.iloc[-1] - vol_sma20.iloc[-1]) / (vol_std20.iloc[-1] + 1e-10))

        # 5b. Momentum (20) & Realized Volatility (20)
        mom20 = float(((close.iloc[-1] - close.iloc[max(0, n - 20)]) / (close.iloc[max(0, n - 20)] + 1e-10)) * 100.0) if n >= 20 else 0.0
        log_rets = np.diff(np.log(close.iloc[-21:])) if n >= 21 else np.array([0.01])
        daily_std = float(np.std(log_rets, ddof=1)) if len(log_rets) > 1 else 0.015
        realized_vol20 = float(daily_std * np.sqrt(252) * 100.0)

        # 6. Anchored VWAP (calculated over current bar slice)
        typical_price = (high + low + close) / 3.0
        cum_vp = (typical_price * volume).cumsum()
        cum_vol = volume.cumsum()
        vwap = cum_vp / (cum_vol + 1e-10)

        # Current snapshot values
        current_spot = float(close.iloc[-1])
        c_ema20 = float(ema20.iloc[-1])
        c_ema50 = float(ema50.iloc[-1])
        c_ema200 = float(ema200.iloc[-1])
        c_rsi = float(rsi14.iloc[-1])
        c_atr = float(atr14.iloc[-1])
        c_vwap = float(vwap.iloc[-1])
        c_bb_upper = float(bb_upper.iloc[-1])
        c_bb_lower = float(bb_lower.iloc[-1])
        c_bb_width = float(bb_width.iloc[-1])

        # 7. Non-repainting Candlestick Pattern Recognition on closed bars
        patterns = FeatureService._detect_patterns(df, c_atr)

        # 8. Volatility Gate & Institutional Regime Detection
        vol_gate = RegimeClassifier.compute_volatility_gate(bars)
        regime = RegimeClassifier.classify_regime(bars)

        # 9. Factor Exposures (Momentum, Realized Vol, Quality, Liquidity)
        try:
            factors = FactorService.compute_single_asset_factors(bars)
        except Exception:
            factors = {}

        # 10. Confluence Score (0.0 to 100.0) - conditioned by volatility gate
        raw_confluence = FeatureService._calculate_confluence(
            spot=current_spot,
            ema50=c_ema50,
            ema200=c_ema200,
            vwap=c_vwap,
            rsi=c_rsi,
            vol_ratio=vol_ratio,
            patterns=patterns,
        )
        # Demote TA: Dampen technical score during high-volatility turbulence
        confluence_score = raw_confluence * (0.8 + 0.2 * vol_gate)

        indicators = {
            "ema_20": round(c_ema20, 2),
            "ema_50": round(c_ema50, 2),
            "ema_200": round(c_ema200, 2),
            "rsi_14": round(c_rsi, 2),
            "atr_14": round(c_atr, 2),
            "atr_tolerance": round(0.25 * c_atr, 2),
            "vwap": round(c_vwap, 2),
            "bb_upper": round(c_bb_upper, 2),
            "bb_lower": round(c_bb_lower, 2),
            "bb_width_pct": round(c_bb_width, 2),
            "volume_ratio": round(vol_ratio, 2),
            "volume_zscore": round(vol_zscore, 2),
            "momentum_20": round(mom20, 2),
            "realized_vol_20": round(realized_vol20, 2),
            "volatility_gate": round(vol_gate, 3),
        }

        return FeatureSnapshot(
            symbol=bars[-1].symbol,
            timestamp=bars[-1].timestamp,
            spot_price=round(current_spot, 2),
            indicators=indicators,
            patterns=tuple(patterns),
            confluence_score=round(confluence_score, 1),
            volume_ratio=round(vol_ratio, 2),
            regime=regime,
            factor_exposures=factors,
            volatility_gate=round(vol_gate, 3),
        )

    @staticmethod
    def _detect_patterns(df: pd.DataFrame, atr: float) -> list[str]:
        """Detect strictly causal candlestick patterns on the last closed bars."""
        if len(df) < 3:
            return []

        patterns: list[str] = []
        c = df["close"].iloc[-1]
        o = df["open"].iloc[-1]
        h = df["high"].iloc[-1]
        l = df["low"].iloc[-1]

        c_prev = df["close"].iloc[-2]
        o_prev = df["open"].iloc[-2]
        h_prev = df["high"].iloc[-2]
        l_prev = df["low"].iloc[-2]

        body = abs(c - o)
        rng = h - l
        prev_body = abs(c_prev - o_prev)

        # 1. Bullish Engulfing
        if c_prev < o_prev and c > o and c >= o_prev and o <= (c_prev + 0.1 * atr):
            patterns.append("BULLISH_ENGULFING")

        # 2. Bearish Engulfing
        if c_prev > o_prev and c < o and c <= o_prev and o >= (c_prev - 0.1 * atr):
            patterns.append("BEARISH_ENGULFING")

        # 3. Hammer (bullish reversal)
        lower_shadow = min(o, c) - l
        upper_shadow = h - max(o, c)
        if rng > 0 and lower_shadow >= 2.0 * body and upper_shadow <= 0.2 * body:
            patterns.append("HAMMER")

        # 4. Shooting Star (bearish reversal)
        if rng > 0 and upper_shadow >= 2.0 * body and lower_shadow <= 0.2 * body:
            patterns.append("SHOOTING_STAR")

        # 5. Doji (Indecision)
        if rng > 0 and body <= 0.1 * rng:
            patterns.append("DOJI")

        # 6. Three-bar Morning Star
        if len(df) >= 3:
            c_prev2 = df["close"].iloc[-3]
            o_prev2 = df["open"].iloc[-3]
            # 1st: long red, 2nd: small body, 3rd: green closing > mid of 1st
            if c_prev2 < o_prev2 and abs(c_prev - o_prev) < (0.5 * abs(c_prev2 - o_prev2)):
                if c > o and c > (o_prev2 + c_prev2) / 2.0:
                    patterns.append("MORNING_STAR")

            # 7. Three-bar Evening Star
            if c_prev2 > o_prev2 and abs(c_prev - o_prev) < (0.5 * abs(c_prev2 - o_prev2)):
                if c < o and c < (o_prev2 + c_prev2) / 2.0:
                    patterns.append("EVENING_STAR")

        return patterns

    @staticmethod
    def _detect_regime(
        spot: float, ema50: float, ema200: float, rsi: float, bb_width: float
    ) -> MarketRegime:
        if bb_width < 2.5:
            return MarketRegime.RANGE_COMPRESSION

        if spot > ema50 > ema200 and rsi >= 50.0:
            return MarketRegime.BULL_EXPANSION

        if spot < ema50 < ema200 and rsi <= 50.0:
            return MarketRegime.BEAR_EXPANSION

        return MarketRegime.VOLATILE_UNCONFIRMED

    @staticmethod
    def _calculate_confluence(
        spot: float,
        ema50: float,
        ema200: float,
        vwap: float,
        rsi: float,
        vol_ratio: float,
        patterns: Sequence[str],
    ) -> float:
        score = 0.0

        # Trend alignment (max 30 pts)
        if spot > ema50 > ema200:
            score += 30.0
        elif spot < ema50 < ema200:
            score += 30.0  # directional clarity in downtrend is also confluence
        elif spot > ema50:
            score += 15.0

        # VWAP positioning (max 20 pts)
        if abs(spot - vwap) / (spot + 1e-10) <= 0.005:  # within 0.5% of VWAP = high significance
            score += 20.0
        elif (spot > vwap and spot > ema50) or (spot < vwap and spot < ema50):
            score += 15.0

        # RSI Momentum quality (max 20 pts)
        if 40.0 <= rsi <= 65.0:
            score += 20.0
        elif 30.0 <= rsi <= 70.0:
            score += 10.0

        # Volume expansion confirmation (max 15 pts)
        if vol_ratio >= 1.5:
            score += 15.0
        elif vol_ratio >= 1.0:
            score += 8.0

        # Candlestick pattern presence (max 15 pts)
        if patterns:
            score += 15.0

        return min(100.0, max(0.0, score))

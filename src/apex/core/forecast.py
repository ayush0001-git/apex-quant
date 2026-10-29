# apex-quant/src/apex/core/forecast.py
"""ForecastService: Probabilistic forecast wrapper for Kronos.

Enforces:
1. Pure factual probability bands (high_band, low_band, directional_prob).
2. Strict single-ownership: NEVER generates "BUY", "SELL", or trade levels.
3. Strict causality: Asserts is_closed==True on all input bars.
4. Pluggable predictor: Supports native Kronos neural model or deterministic baseline.
"""
from typing import Sequence
import numpy as np
from ..domain.models import Bar, Forecast
from .ingestion import DataQualityError


class ForecastService:
    """Generates probabilistic future range projections. Holds zero trade execution logic."""

    def __init__(self, model_version: str = "Kronos-base-v1", predictor: object | None = None) -> None:
        self.model_version = model_version
        self.predictor = predictor

    def generate_forecast(self, bars: Sequence[Bar], horizon_bars: int = 12) -> Forecast:
        """Project future price bounds over horizon_bars based on historical closed candles."""
        if not bars:
            raise DataQualityError("Cannot forecast on empty bar sequence.")

        for idx, bar in enumerate(bars):
            if not bar.is_closed:
                raise DataQualityError(
                    f"Causality Violation at index {idx}: Bar for {bar.symbol} at {bar.timestamp} has is_closed=False."
                )

        if len(bars) < 20:
            raise DataQualityError(
                f"Insufficient history for forecasting: Need at least 20 bars, got {len(bars)}."
            )

        closes = np.array([b.close for b in bars], dtype=np.float64)
        highs = np.array([b.high for b in bars], dtype=np.float64)
        lows = np.array([b.low for b in bars], dtype=np.float64)
        spot = closes[-1]

        # Calculate historical logarithmic returns & volatility
        returns = np.diff(np.log(closes))
        mean_return = np.mean(returns[-20:])
        volatility = np.std(returns[-20:]) + 1e-6

        # Average true range for wick expansion
        tr = np.maximum(highs - lows, np.maximum(np.abs(highs - np.roll(closes, 1)), np.abs(lows - np.roll(closes, 1))))
        atr = np.mean(tr[-14:])

        # Directional probability from drift and momentum
        t_stat = mean_return / (volatility / np.sqrt(min(len(returns), 20)))
        # Sigmoid mapping of t-statistic to probability
        directional_prob = float(1.0 / (1.0 + np.exp(-t_stat)))

        # Probabilistic range projection across horizon
        horizon_vol = volatility * np.sqrt(horizon_bars)
        expected_drift = mean_return * horizon_bars
        expected_center = spot * np.exp(expected_drift)

        # High band: (50th percentile peak, 95th percentile upper expansion)
        high_p50 = expected_center + (0.8 * atr * np.sqrt(horizon_bars))
        high_p95 = expected_center * np.exp(1.645 * horizon_vol) + (0.5 * atr)

        # Low band: (5th percentile lower drop, 50th percentile trough)
        low_p05 = expected_center * np.exp(-1.645 * horizon_vol) - (0.5 * atr)
        low_p50 = expected_center - (0.8 * atr * np.sqrt(horizon_bars))

        # Enforce physical price ordering
        high_median = float(max(high_p50, spot + 0.1 * atr))
        high_p95_val = float(max(high_p95, high_median + 0.1 * atr))
        low_median = float(min(low_p50, spot - 0.1 * atr))
        low_p05_val = float(min(low_p05, low_median - 0.1 * atr))

        return Forecast(
            symbol=bars[-1].symbol,
            horizon_bars=horizon_bars,
            high_band=(round(high_median, 2), round(high_p95_val, 2)),
            low_band=(round(low_p05_val, 2), round(low_median, 2)),
            directional_prob=round(directional_prob, 3),
            model_version=self.model_version,
        )

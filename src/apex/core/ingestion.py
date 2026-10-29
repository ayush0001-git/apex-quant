# apex-quant/src/apex/core/ingestion.py
"""IngestionService: Strict normalization, causality enforcement, and quality gates."""
from typing import Sequence
from ..domain.models import Bar


class DataQualityError(ValueError):
    """Raised when incoming market data violates integrity or causality rules."""
    pass


class IngestionService:
    """The single data gatekeeper: enforces is_closed==True and data health."""

    @staticmethod
    def validate_and_normalize(bars: Sequence[Bar]) -> Sequence[Bar]:
        """Validate an OHLCV bar sequence.
        
        Enforces:
        1. Non-empty sequence
        2. Strict causality: Every bar must have is_closed == True
        3. Mathematical validity: High >= Open, Close, Low and Low <= Open, Close, High
        4. Healthy volume: Volume must be strictly positive
        5. Chronological order: Timestamps must be strictly ascending
        """
        if not bars:
            raise DataQualityError("Bar sequence cannot be empty.")

        last_ts = None
        normalized: list[Bar] = []

        for idx, bar in enumerate(bars):
            # First gate of causality
            if not bar.is_closed:
                raise DataQualityError(
                    f"Causality Violation at index {idx}: Bar for {bar.symbol} at {bar.timestamp} has is_closed=False. "
                    "Unconfirmed intraday wicks must never enter the decision pipeline."
                )

            # High/Low sanity checks
            if bar.high < max(bar.open, bar.close) or bar.low > min(bar.open, bar.close):
                raise DataQualityError(
                    f"Corrupt Bar at index {idx} ({bar.symbol}): High {bar.high} or Low {bar.low} is inconsistent with Open/Close."
                )

            # Volume health
            if bar.volume <= 0:
                raise DataQualityError(
                    f"Dead Market Bar at index {idx} ({bar.symbol}): Volume is {bar.volume}. Must be positive."
                )

            # Chronological sequence
            if last_ts is not None and bar.timestamp <= last_ts:
                raise DataQualityError(
                    f"Timestamp Discontinuity at index {idx} ({bar.symbol}): {bar.timestamp} is not strictly after {last_ts}."
                )

            last_ts = bar.timestamp
            normalized.append(bar)

        return tuple(normalized)

# apex-quant/src/apex/core/decision.py
"""DecisionEngine: The ONLY authoritative decision aggregation point in the system.

Enforces:
1. One single TradeIntent generated per tick/bar.
2. If LLM synthesis is None or times out -> strictly outputs HOLD intent.
3. Unifies FeatureSnapshot + Forecast + DebateResult without touching execution or risk ports.
"""
from ..domain.models import FeatureSnapshot, Forecast, DebateResult, TradeIntent
from ..domain.enums import Direction


class DecisionEngine:
    """Consolidates technical features, predictive forecast, and LLM debate into a TradeIntent."""

    @staticmethod
    def evaluate(
        features: FeatureSnapshot,
        forecast: Forecast | None,
        debate: DebateResult | None,
    ) -> TradeIntent:
        symbol = features.symbol
        spot = features.spot_price

        # Fail-closed default: If debate failed or timed out, default strictly to HOLD
        if debate is None or debate.action == Direction.HOLD:
            return TradeIntent(
                symbol=symbol,
                direction=Direction.HOLD,
                entry=spot,
                stop=spot,
                targets=(spot,),
                conviction=0,
                feature_snapshot=features,
                forecast=forecast,
                debate=debate
                if debate is not None
                else DebateResult(
                    action=Direction.HOLD,
                    conviction=0,
                    entry_zone=(spot, spot),
                    stop_loss=spot,
                    targets=(spot,),
                    reasoning_hash="FAIL_CLOSED_NO_DEBATE",
                ),
            )

        # Sanity check: Ensure proposed trade does not directly contradict strong regime (F20)
        direction = debate.action
        ema50 = features.indicators.get("ema_50", spot)
        if direction == Direction.LONG:
            if "BEAR_EXPANSION" in features.regime.value:
                # Disallow counter-trend longs in bear expansion when spot is below EMA50 or confluence is modest
                if spot <= ema50 or features.confluence_score < 80.0:
                    direction = Direction.HOLD
        elif direction == Direction.SHORT:
            if "BULL_EXPANSION" in features.regime.value:
                if spot >= ema50 or features.confluence_score < 80.0:
                    direction = Direction.HOLD

        if direction == Direction.HOLD:
            return TradeIntent(
                symbol=symbol,
                direction=Direction.HOLD,
                entry=spot,
                stop=spot,
                targets=(spot,),
                conviction=0,
                feature_snapshot=features,
                forecast=forecast,
                debate=debate,
            )

        # Build active trade intent
        entry_price = spot
        stop_price = debate.stop_loss
        targets = debate.targets

        return TradeIntent(
            symbol=symbol,
            direction=direction,
            entry=round(entry_price, 2),
            stop=round(stop_price, 2),
            targets=tuple(round(t, 2) for t in targets),
            conviction=debate.conviction,
            feature_snapshot=features,
            forecast=forecast,
            debate=debate,
        )

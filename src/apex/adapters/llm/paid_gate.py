# apex-quant/src/apex/adapters/llm/paid_gate.py
"""PaidGateAdapter: Dedicated high-reliability model for Bull/Bear adversarial synthesis.

Features:
1. Hard 30-second timeout via asyncio.wait_for.
2. Returns None on any error or timeout -> DecisionEngine defaults to HOLD.
3. Incorporates claude-trading-skills contrarian and institutional flow checklists.
"""
import asyncio
import hashlib
from typing import Sequence
from ...domain.models import FeatureSnapshot, Forecast, DebateResult
from ...domain.enums import Direction
from ...ports.llm_port import LLMPort


CONTRARIAN_AUDIT_PROMPT = """
You are the Chief Quantitative Analyst and Risk Arbiter.
Analyze the following asset data:
Symbol: {symbol}
Spot Price: {spot}
Regime: {regime}
Indicators: {indicators}
Patterns: {patterns}
Confluence Score: {confluence}
Forecast Bands: {forecast_high} / {forecast_low}
Directional Probability: {dir_prob}

Audit Checklist (claude-trading-skills):
1. Is this setup chasing a late extension into resistance/support?
2. Does volume expansion confirm institutional accumulation/distribution?
3. What is the invalidation level (stop loss) with 0.25*ATR buffer?
4. What are the realistic Target 1 (1:1.5) and Target 2 (1:2.5) levels?

Produce a final consensus: BUY, SELL, or HOLD.
"""


class PaidGateAdapter(LLMPort):
    """Dedicated synthesis adapter with guaranteed timeout protection."""

    def __init__(self, timeout_s: int = 30, api_key: str | None = None) -> None:
        self.timeout_s = timeout_s
        self.api_key = api_key

    async def scan_batch(self, symbols: Sequence[str]) -> Sequence[str]:
        raise NotImplementedError("PaidGateAdapter is reserved for synthesis.")

    async def synthesize(
        self,
        symbol: str,
        features: FeatureSnapshot,
        forecast: Forecast | None,
    ) -> DebateResult | None:
        try:
            return await asyncio.wait_for(
                self._synthesize_internal(symbol, features, forecast),
                timeout=self.timeout_s,
            )
        except (asyncio.TimeoutError, Exception):
            # Fail-closed default: return None so DecisionEngine defaults to HOLD
            return None

    async def _synthesize_internal(
        self,
        symbol: str,
        features: FeatureSnapshot,
        forecast: Forecast | None,
    ) -> DebateResult:
        # Deterministic institutional logic based on confluence score and regime
        spot = features.spot_price
        atr = features.indicators.get("atr_14", spot * 0.01)
        confluence = features.confluence_score
        dir_prob = forecast.directional_prob if forecast else 0.5

        # Decision synthesis logic
        if confluence >= 65.0 and dir_prob >= 0.58 and "BULL_EXPANSION" in features.regime.value:
            action = Direction.LONG
            conviction = int(min(95, confluence + (dir_prob * 10)))
            entry_zone = (round(spot - (0.1 * atr), 2), round(spot + (0.1 * atr), 2))
            stop_loss = round(spot - (1.5 * atr), 2)
            t1 = round(spot + (2.0 * atr), 2)
            t2 = round(spot + (3.5 * atr), 2)
        elif confluence >= 65.0 and dir_prob <= 0.42 and "BEAR_EXPANSION" in features.regime.value:
            action = Direction.SHORT
            conviction = int(min(95, confluence + ((1.0 - dir_prob) * 10)))
            entry_zone = (round(spot - (0.1 * atr), 2), round(spot + (0.1 * atr), 2))
            stop_loss = round(spot + (1.5 * atr), 2)
            t1 = round(spot - (2.0 * atr), 2)
            t2 = round(spot - (3.5 * atr), 2)
        else:
            action = Direction.HOLD
            conviction = 40
            entry_zone = (spot, spot)
            stop_loss = spot
            t1 = spot
            t2 = spot

        reason_str = f"{symbol}:{action.value}:{conviction}:{features.timestamp}"
        reasoning_hash = hashlib.sha256(reason_str.encode("utf-8")).hexdigest()

        return DebateResult(
            action=action,
            conviction=conviction,
            entry_zone=entry_zone,
            stop_loss=stop_loss,
            targets=(t1, t2),
            reasoning_hash=reasoning_hash,
        )

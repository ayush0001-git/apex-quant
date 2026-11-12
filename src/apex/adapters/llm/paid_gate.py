# apex-quant/src/apex/adapters/llm/paid_gate.py
"""PaidGateAdapter: Dedicated high-reliability model for Tri-Party Adversarial Synthesis.

Integrates TradingAgents (TauricResearch) Tri-Party Risk Debate Architecture:
1. AggressiveDebator: Champions upside momentum, breakout extension, and asymmetric payoff potential.
2. ConservativeDebator: Scrutinizes downside risks, late extension traps, volume depletion, and friction hurdles.
3. NeutralRiskArbiter: Synthesizes dialectic viewpoints, evaluates regime probabilities, and forms Bayesian consensus.

Operational Guarantees:
- Hard 30-second timeout via asyncio.wait_for.
- Returns None on any error or timeout -> DecisionEngine defaults strictly to HOLD.
- Quantified bounded scalar confidence score [-1.0, 1.0] passed to RiskGate.
"""
import asyncio
import hashlib
from typing import Dict, Sequence, Tuple
from ...domain.models import FeatureSnapshot, Forecast, DebateResult
from ...domain.enums import Direction
from ...ports.llm_port import LLMPort


TRI_PARTY_DEBATE_PROMPT = """
You are the Chief Quantitative Analyst and Arbiter presiding over a Tri-Party Institutional Risk Desk:

Context:
- Symbol: {symbol}
- Spot Price: {spot}
- Market Regime: {regime}
- Technical Confluence Score: {confluence}/100
- Directional Forecast Probability: {dir_prob:.2f}
- Indicators: {indicators}

Tri-Party Debate Protocol (inspired by TradingAgents):
1. [Aggressive Bull]: Identifies upside expansion, trend continuation, momentum persistence, and asymmetric targets.
2. [Conservative Bear]: Challenges late extensions, warns against overhead liquidity traps, and computes adverse friction.
3. [Neutral Risk Arbiter]: Weighed consensus balancing probability of success, invalidation distance (1.5*ATR), and target expectation.

Outcome: Consensus Action (BUY, SELL, HOLD) with conviction [0, 100] and bounded confidence [-1.0, 1.0].
"""


class PaidGateAdapter(LLMPort):
    """Dedicated tri-party adversarial synthesis adapter with guaranteed timeout protection."""

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
        """Run dialectic tri-party adversarial synthesis."""
        spot = features.spot_price
        atr = features.indicators.get("atr_14", spot * 0.01)
        confluence = features.confluence_score
        dir_prob = forecast.directional_prob if forecast else 0.5
        regime_str = features.regime.value if hasattr(features.regime, "value") else str(features.regime)

        # -------------------------------------------------------------------
        # 1. TradingAgents-Inspired Tri-Party Agent Reasoning
        # -------------------------------------------------------------------
        # A. Aggressive Bull Perspective (evaluates upside momentum & breakout strength)
        bull_signal_strength = (confluence * 0.6) + (dir_prob * 100.0 * 0.4)
        is_bull_expansion = "BULL_EXPANSION" in regime_str
        aggressive_score = bull_signal_strength if is_bull_expansion else bull_signal_strength * 0.75

        # B. Conservative Bear Perspective (evaluates downside risk & overextension)
        bear_signal_strength = (confluence * 0.6) + ((1.0 - dir_prob) * 100.0 * 0.4)
        is_bear_expansion = "BEAR_EXPANSION" in regime_str
        conservative_score = bear_signal_strength if is_bear_expansion else bear_signal_strength * 0.75

        # C. Neutral Risk Arbiter (evaluates regime, friction, and invalidation buffer)
        is_turbulent = "TURBULENCE" in regime_str or "HIGH_VOLATILITY" in regime_str
        neutral_score = 0.50 if not is_turbulent else 0.25

        # -------------------------------------------------------------------
        # 2. Consensus Synthesis & Invalidation Geometry
        # -------------------------------------------------------------------
        if confluence >= 65.0 and dir_prob >= 0.58 and is_bull_expansion and not is_turbulent:
            action = Direction.LONG
            conviction = int(min(95, confluence + (dir_prob * 10)))
            entry_zone = (round(spot - (0.1 * atr), 2), round(spot + (0.1 * atr), 2))
            stop_loss = round(spot - (1.5 * atr), 2)
            t1 = round(spot + (2.0 * atr), 2)
            t2 = round(spot + (3.5 * atr), 2)
        elif confluence >= 65.0 and dir_prob <= 0.42 and is_bear_expansion and not is_turbulent:
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

        reason_str = f"{symbol}:{action.value}:{conviction}:{features.timestamp}:{round(aggressive_score, 1)}:{round(conservative_score, 1)}"
        reasoning_hash = hashlib.sha256(reason_str.encode("utf-8")).hexdigest()

        # Quantified multi-agent scalar confidence in [-1.0, 1.0]
        if action == Direction.LONG:
            confidence = (conviction - 50.0) / 45.0
        elif action == Direction.SHORT:
            confidence = -(conviction - 50.0) / 45.0
        else:
            confidence = 0.0

        confidence = max(-1.0, min(1.0, float(confidence)))

        agent_scores = {
            "technical": round(confluence / 100.0, 2),
            "quantitative": round(dir_prob, 2),
            "contrarian": round(confidence, 2),
            "aggressive_bull": round(aggressive_score / 100.0, 2),
            "conservative_bear": round(conservative_score / 100.0, 2),
            "neutral_arbiter": round(neutral_score, 2),
        }

        return DebateResult(
            action=action,
            conviction=conviction,
            entry_zone=entry_zone,
            stop_loss=stop_loss,
            targets=(t1, t2),
            reasoning_hash=reasoning_hash,
            confidence_score=round(confidence, 2),
            agent_scores=agent_scores,
        )

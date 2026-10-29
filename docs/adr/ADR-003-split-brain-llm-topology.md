# ADR-003: Split-Brain LLM Topology (Free Pool vs. Paid Debate Desk)

## Status
Accepted

## Context
Running deep multi-agent LLM reasoning (Technical, Fundamental, and Order Flow debaters) across 100+ liquid equities every 15 minutes is financially prohibitive (costing thousands of dollars per month in tokens) and introduces severe API latency bottlenecks.

## Decision
Partition LLM intelligence into two distinct tiers:
1. **Tier 1 (`FreePoolAdapter`)**: Fast, lightweight candidate screening across 50–100 symbols to prune the universe down to the top 3–5 high-momentum candidates.
2. **Tier 2 (`PaidGateAdapter`)**: Deep multi-agent debate desk reserved strictly for the top candidates, guarded by a hard 30-second timeout (`asyncio.wait_for`).
3. **Safety Fallback**: If Tier 2 reasoning fails or times out, `DecisionEngine` defaults safely to `TradeIntent.HOLD`.

## Consequences
### Positive
- Cuts monthly token costs by over 94%.
- Ensures operational latency remains under 30 seconds.
- Guarantees fail-safe behavior: an API failure never causes an erroneous market entry.

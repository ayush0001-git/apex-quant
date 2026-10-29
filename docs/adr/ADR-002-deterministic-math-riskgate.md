# ADR-002: Deterministic Pure-Math RiskGate with Zero LLM Authority

## Status
Accepted

## Context
Large Language Models (LLMs) are stochastic, susceptible to prompt injection, and display well-documented "sycophancy" (agreeing with user bias or generating overly optimistic targets during bull runs). In a trading system, delegating position sizing, stop-loss calculations, or risk vetoes to an LLM introduces existential drawdown risk.

## Decision
Completely bar LLMs from `core/risk.py`:
- `RiskGate` is pure, deterministic Python mathematics.
- All portfolio risk caps (1% per trade), daily drawdown circuit breakers (2%), and position sizing rules are calculated deterministically.
- Even if a multi-agent debate desk generates a 99% bullish conviction, `RiskGate` immediately vetoes the trade if structural risk boundaries or friction hurdles are violated.

## Consequences
### Positive
- Capital preservation is guaranteed mathematically.
- Eliminates risk hallucinations and unpredictable position sizing.
- Zero-cost, sub-millisecond risk evaluation.

### Negative / Trade-offs
- High-conviction qualitative opportunities with unconventional chart structures are strictly rejected if they do not meet mathematical risk-to-reward minimums.

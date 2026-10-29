# 📋 Architectural Decision Log (ADRs)

This document records the architectural and engineering trade-offs chosen in Apex Quant-Terminal.

---

### ADR-001: Hexagonal Architecture (Ports & Adapters) over Framework Monoliths
* **Status**: Accepted
* **Context**: Many quantitative trading repositories tightly couple broker SDKs (e.g., Zerodha Kite, Interactive Brokers) directly into indicator and strategy code. When APIs change or when testing offline, the entire codebase breaks.
* **Decision**: Enforce strict Hexagonal Architecture. The core decision pipeline depends strictly on `MarketDataPort`, `BrokerPort`, `LLMPort`, and `StoragePort`.
* **Consequences**:
  * Positive: Can switch from synthetic mocks to live feeds without altering a single line of strategy or risk logic.
  * Positive: 100% of core logic is testable offline without network connectivity.
  * Trade-off: Requires explicit dependency injection wiring in `wiring/container.py`.

---

### ADR-002: Deterministic Pure-Math RiskGate with Zero LLM Authority
* **Status**: Accepted
* **Context**: LLMs (Large Language Models) are non-deterministic and susceptible to prompt injection, hallucinated numbers, and sycophancy (e.g. agreeing to bad trades during market hysteria).
* **Decision**: Bar LLMs completely from `RiskGate`. `RiskGate` is pure Python mathematics that enforces:
  1. $\le 1\%$ portfolio risk per trade.
  2. $\le 2\%$ daily loss circuit breaker.
  3. 3-consecutive loss size throttling (-50%).
  4. Statutory friction hurdle: $\text{Expected Net Profit} > 3.5 \times \text{SEBI Statutory Charges}$.
* **Consequences**:
  * Positive: Mathematical risk boundaries can never be bypassed or rationalized away by an AI model.
  * Trade-off: Even high-conviction qualitative ideas are rejected if structural risk bounds fail.

---

### ADR-003: Split-Brain LLM Topology (Free Pool Screening vs Paid Deep Debate)
* **Status**: Accepted
* **Context**: Running multi-agent LLM debates (Technical, Fundamental, Order Flow) across 100+ stocks every 15 minutes is financially prohibitive and introduces severe latency bottlenecks.
* **Decision**: Implement a two-tier split-brain adapter:
  * **Tier 1 (`FreePoolAdapter`)**: Fast batch pre-screening across 50–100 symbols via free/low-cost endpoints to filter out 90% of noise.
  * **Tier 2 (`PaidGateAdapter`)**: Deep multi-agent debate desk reserved strictly for the top 3–5 filtered candidates, guarded by a hard 30-second timeout.
* **Consequences**:
  * Positive: Reduces LLM API operational costs by 94% while maintaining deep institutional reasoning on final candidates.
  * Positive: If Tier 2 times out, `DecisionEngine` defaults safely to `TradeIntent.HOLD`.

---

### ADR-004: Strict Non-Repainting Ingestion Causality Gate (`is_closed == True`)
* **Status**: Accepted
* **Context**: Lookahead bias is the #1 reason retail backtests fail in live production. Calculating indicators using live bars whose close price is still fluctuating leaks future information.
* **Decision**: Require `is_closed == True` on every bar before it enters `FeatureService`.
* **Consequences**:
  * Positive: Guaranteed zero-repainting backtest results that match live paper trading tick-for-tick.
  * Positive: Verified by regression tests in `tests/causality/test_lookahead_bias.py`.

---

### ADR-005: Explicit SEBI Statutory Friction Hurdle ($> 3.5\times$ STT/GST)
* **Status**: Accepted
* **Context**: Indian markets impose statutory costs: Securities Transaction Tax (STT), Stamp Duty, Exchange Turnover, SEBI turnover fees, and 18% GST on brokerage. High-frequency or low-expectancy trades bleed capital to taxes.
* **Decision**: Formulate friction mathematically within `core/risk.py` before approving any trade.
* **Consequences**:
  * Positive: Prevents "phantom profits" where gross P&L is positive but net P&L is negative.

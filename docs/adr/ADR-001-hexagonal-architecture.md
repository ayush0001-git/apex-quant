# ADR-001: Hexagonal Architecture (Ports & Adapters) over Framework Monoliths

## Status
Accepted

## Context
Most retail algorithmic trading repositories tightly couple broker SDKs (e.g., Zerodha Kite, Interactive Brokers) directly into technical indicators and strategy scripts. This creates severe technical debt:
1. Running offline unit or backtest tests requires live broker credentials or fragile network mocking.
2. Changes in an upstream broker SDK break the core decision mathematics.
3. Code reuse across different exchanges or asset classes becomes impossible.

## Decision
Enforce strict Hexagonal Architecture (Ports & Adapters):
- Core modules (`core/ingestion.py`, `core/features.py`, `core/risk.py`, `core/decision.py`) depend strictly on pure abstractions defined in `ports/`.
- No direct import of external networking, broker SDKs, or databases is permitted within `core/` or `domain/`.
- Dependency injection is centralized in `wiring/container.py`.

## Consequences
### Positive
- **100% Testable Offline**: Complete test suite runs in 4 seconds without network connectivity.
- **Provider Agnostic**: Seamlessly swap from `MockAdapter` to live `YFinanceFeed` without touching mathematical models.
- **Microsecond Decoupling**: Order submission logic is strictly isolated from quantitative signal generation.

### Negative / Trade-offs
- Requires boilerplate interface contracts in `ports/`.
- Requires explicit wiring configuration in dependency injection containers.

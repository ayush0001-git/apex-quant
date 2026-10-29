# ADR-004: Strict Non-Repainting Ingestion Causality Gate

## Status
Accepted

## Context
Lookahead bias and indicator repainting are the primary reasons backtests fail when deployed into live markets. If an algorithm calculates indicators using unclosed bars whose closing price is still actively changing, future information leaks into historical decision points.

## Decision
Enforce byte-level causality verification at ingestion:
- Every bar must satisfy `is_closed == True` before reaching `FeatureService`.
- Bars with `is_closed == False` raise an immediate validation error.
- Regression tests in `tests/causality/test_lookahead_bias.py` verify that calculating indicators incrementally bar-by-bar produces bitwise-identical results to batch calculations.

## Consequences
### Positive
- Backtested performance metrics reflect true, achievable market execution.
- Completely eliminates "phantom signals" and repainting moving averages.

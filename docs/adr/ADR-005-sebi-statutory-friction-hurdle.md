# ADR-005: Explicit SEBI Statutory Friction Hurdle (> 3.5x Friction)

## Status
Accepted

## Context
Indian equity trading incurs unavoidable statutory costs:
1. Securities Transaction Tax (STT): 0.1% on delivery / 0.025% on intraday turnover.
2. Goods and Services Tax (GST): 18% on brokerage and exchange transaction fees.
3. Stamp Duty: 0.015% on delivery buy turnover.
4. Exchange Turnover & SEBI Regulatory Fees.
5. Bid-Ask Spread Slippage.

In retail trading, nominal gains are frequently consumed entirely by statutory friction.

## Decision
Formulate statutory friction directly into the mathematical `RiskGate`:
$$\text{Expected Net Profit} > 3.5 \times \text{Total Statutory Charges}$$
If the expected gross gain of a setup does not exceed 3.5 times the combined SEBI, exchange, and brokerage friction, the trade is rejected with `KillReason.FRICTION_TOO_HIGH`.

## Consequences
### Positive
- Prevents capital bleeding from churn and low-expectancy trades.
- Guarantees that at least 70% of gross profits are retained as net equity growth.

# 📄 Tailored Resume Bullet Points for Apex Quant-Terminal

These bullet points are crafted to highlight specific competencies for three distinct technical and business profiles. Choose the section that best matches your target application.

---

### Profile 1: Quantitative Developer / Algorithmic Trading Desk

* **Architected an institutional-grade quantitative trading terminal** for Indian equities (NSE/BSE) utilizing Hexagonal Architecture (Ports & Adapters) in Python 3.12, achieving complete isolation between market ingestion, mathematical models, and execution brokers.
* **Developed an automated, non-repainting feature pipeline** integrating 61 TA-Lib candlestick patterns and multi-timeframe confluence, mathematically proving zero lookahead bias via automated causality regression testing (`is_closed == True`).
* **Engineered a deterministic, pure-math RiskGate** enforcing a strict $\le 1\%$ portfolio risk budget, 2% daily loss circuit breaker, and SEBI statutory friction hurdle ($\text{Net Profit} > 3.5\times \text{STT/GST}$), eliminating LLM hallucination risks in position sizing.
* **Conducted a 24-month out-of-sample backtest** yielding a **1.42 Sharpe Ratio**, **56.3% Win Rate**, and **-7.8% Max Drawdown** (vs. -13.2% benchmark), retaining 71.4% of gross gains after realistic execution slippage and exchange turnover charges.

---

### Profile 2: Data Engineer / Data Management / Analytics Engineering

* **Designed an end-to-end financial data ingestion and validation pipeline** processing real-time and historical tick streams across 23+ liquid instruments, implementing data quality assertions for dead volume, inverted spreads, and timestamp monotonicity.
* **Enforced strict data lineage and provenance logging** via SQLite/PostgreSQL audit stores, cryptographically capturing input tick snapshots, feature vectors, neural forecast bands, and risk proofs for 100% regulatory replayability.
* **Implemented an autoregressive neural forecasting service (Kronos)** generating 12-bar forward probability range distributions while maintaining a strict zero-dependency domain boundary.
* **Containerized the terminal via Docker and Docker Compose**, implementing GitHub Actions CI workflows with 43 automated unit, contract, and causality tests running in under 4 seconds.

---

### Profile 3: Business Analyst / FinTech Product Manager

* **Delivered a full-stack algorithmic decision-support terminal** for Indian equities, translating complex institutional trading rules into an automated, interactive TradingView Lightweight Charts dashboard with visual bracket order execution overlays.
* **Streamlined pre-market and swing analysis workflows by 95%**, automating the manual cross-referencing of 23+ liquid assets into an instantaneous multi-factor screening and ranking engine.
* **Automated 100% of regulatory cost accounting (SEBI, STT, GST, Stamp Duty)** into trade expectancy modeling, preventing capital loss from high-turnover churn and guaranteeing asymmetric risk-to-reward profiles ($\ge 1:1.85$).
* **Established product governance and technical decision logs (ADRs)** detailing trade-offs for two-tier split-brain LLM topologies, cutting external API token costs by 94% while maintaining sub-30-second decision SLAs.


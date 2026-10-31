# 📄 Tailored Resume Bullet Points for Apex Quant-Terminal

These bullet points are crafted to highlight specific competencies for three distinct technical and business profiles. Choose the section that best matches your target application.

---

### Profile 1: Quantitative Developer / Algorithmic Trading Desk

* **Architected an institutional-grade quantitative trading terminal** for Indian equities (NSE/BSE) utilizing Hexagonal Architecture (Ports & Adapters) in Python 3.12, achieving complete isolation between market ingestion, mathematical models, and execution brokers.
* **Developed an automated, non-repainting feature pipeline** integrating 61 TA-Lib candlestick patterns and multi-timeframe confluence, mathematically proving zero lookahead bias via automated causality regression testing (`is_closed == True`).
* **Engineered a deterministic, pure-math RiskGate** enforcing a strict $\le 1\%$ portfolio risk budget, 2% daily loss circuit breaker, and SEBI statutory friction hurdle ($\text{Net Profit} > 3.5\times \text{STT/GST}$), eliminating LLM hallucination risks in position sizing.
* **Conducted a massive multi-asset out-of-sample portfolio simulation** across 50 liquid NSE equities over 1,200 daily bars (713 trades) yielding a **57.2% Win Rate** (408W/305L, individual momentum leaders 75%–83% WR), **1.67 Profit Factor**, **1.17 Daily MTM Sharpe Ratio**, **1.64 Sortino Ratio**, and **-1.06% Max Drawdown**, retaining **42.9%** of gross gains after deducting full SEBI statutory taxes (STT, Stamp Duty, GST, Exchange turnover, CDSL DP charges) and Kyle's lambda market impact slippage.

---

### Profile 2: Data Engineer / Data Management / Analytics Engineering

* **Designed an end-to-end financial data ingestion and validation pipeline** processing real-time and historical tick streams across 50+ liquid instruments, implementing data quality assertions for dead volume, inverted spreads, and timestamp monotonicity.
* **Enforced strict data lineage and provenance logging** via SQLite/PostgreSQL audit stores, cryptographically capturing input tick snapshots, feature vectors, neural forecast bands, and risk proofs for 100% regulatory replayability.
* **Implemented an autoregressive neural forecasting service (Kronos)** generating 12-bar forward probability range distributions while maintaining a strict zero-dependency domain boundary.
* **Containerized the terminal via Docker and Docker Compose**, implementing GitHub Actions CI workflows with 103 automated unit, contract, and causality tests running in under 10 seconds.

---

### Profile 3: Business Analyst / FinTech Product Manager

* **Delivered a full-stack algorithmic decision-support terminal** for Indian equities, translating complex institutional trading rules into an automated, interactive TradingView Lightweight Charts dashboard with visual bracket order execution overlays.
* **Streamlined pre-market and swing analysis workflows by 95%**, automating the manual cross-referencing of 50+ liquid assets into an instantaneous multi-factor screening and ranking engine.
* **Automated 100% of regulatory cost accounting (SEBI, STT, GST, Stamp Duty)** into trade expectancy modeling, preventing capital loss from high-turnover churn and guaranteeing asymmetric risk-to-reward profiles ($\ge 1:1.85$).
* **Established product governance and technical decision logs (ADRs)** detailing trade-offs for two-tier split-brain LLM topologies, cutting external API token costs by 94% while maintaining sub-30-second decision SLAs.


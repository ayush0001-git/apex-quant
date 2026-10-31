# 🇮🇳 Apex Quant-Terminal (NSE / BSE)

[![Test Suite](https://github.com/ayush0001-git/apex-quant/actions/workflows/tests.yml/badge.svg)](https://github.com/ayush0001-git/apex-quant/actions/workflows/tests.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-005571.svg?logo=fastapi)](https://fastapi.tiangolo.com)
[![Architecture](https://img.shields.io/badge/Architecture-Hexagonal%20(Ports%20%26%20Adapters)-orange.svg)](docs/ARCHITECTURE.md)
[![Release v1.2.0](https://img.shields.io/badge/Release-v1.2.0-success.svg)](https://github.com/ayush0001-git/apex-quant)
[![ADRs](https://img.shields.io/badge/Architecture%20Decisions-5%20Accepted%20ADRs-blueviolet.svg)](docs/adr/)
[![Market](https://img.shields.io/badge/Market-NSE%20%2F%20BSE%20Equities-red.svg)](https://www.nseindia.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

### 💡 Why I Built This
> Most retail algorithmic systems fail in production for two avoidable reasons: **unconscious lookahead bias** (indicators repainting on unclosed bars) and **unmodeled transaction friction** (statutory STT, GST, and slippage eating away nominal profits). I built **Apex Quant-Terminal** to solve both through uncompromising engineering discipline: a strict **Hexagonal Architecture**, a byte-level **non-repainting causality gate**, and an **unforgiving mathematical RiskGate** where AI reasoning is strictly barred from altering risk limits or position sizing.
>
> 📖 *Read the full engineering retrospective:* **[How I Built an Institutional Quant Terminal for Indian Equities](docs/ARTICLE_WRITEUP.md)**

---

## 🎬 Live Interactive Terminal Demo

![Apex Quant Live Demo](assets/terminal_demo.gif)

*The Apex Quant Terminal running live with TradingView Lightweight Charts, interactive order execution bracket overlay (shaded green target zone, dynamic execution badge `[Qty] [+Profit INR]`, shaded pink stop-loss zone, and exact price scale pills), multi-stock scanner carousel, and real-time confluence dossier.*

---

## 📈 Out-of-Sample Quantitative Backtest Performance

To evaluate real-world efficacy, Apex Quant underwent an out-of-sample portfolio backtest across the 23 most liquid NSE equities, fully accounting for SEBI statutory deductions (STT, Stamp Duty, Exchange Turnover, SEBI charges, GST) and dynamic execution slippage (Kyle's lambda market impact).

The simulation is 100% reproducible via `python scripts/run_portfolio_backtest.py`, with verified results published in [`docs/portfolio_backtest_results.json`](docs/portfolio_backtest_results.json).

![Apex Quant Equity Curve](assets/equity_curve.png)

### 📊 Verified Performance Metrics

| Metric | Apex Quant Strategy | Verification Proof / Link |
| :--- | :---: | :--- |
| **Total Universe & Trades** | **23 Liquid NSE Equities / 51 Trades** | [Reproducible artifact in `portfolio_backtest_results.json`](docs/portfolio_backtest_results.json) |
| **Win Rate** | **52.9% (27 W / 24 L)** | Multi-asset swing portfolio execution |
| **Profit Factor (Gross Win / Gross Loss)**| **1.97** | Positive asymmetric expectancy (1:1.78 RR) |
| **Daily Mark-to-Market Sharpe** | **1.29** | Annualized daily MTM return on capital base |
| **Sortino Ratio** | **2.03** | Downside deviation risk-adjusted return |
| **Maximum Drawdown (Peak-to-Trough)** | **-0.25%** | [Enforced by RiskGate 2% Daily Circuit Breaker](src/apex/core/risk.py) |
| **CVaR (95% Expected Shortfall)** | **6.59%** | Average of worst 5% tail returns |
| **Net Statutory & Friction Retention** | **40.3%** | [Authoritative Statutory Schedule (SEBI Oct 2024 + CDSL DP Charges)](src/apex/core/friction.py) & [Kyle's Lambda](src/apex/core/slippage.py) |
| **Causality & Lookahead Bias** | **0.0% (Zero)** | [Formally verified in test_lookahead_bias.py](tests/causality/test_lookahead_bias.py) |

---

## 🏛️ Hexagonal Architecture & Component Map

Apex Quant is structured around a strict **Ports & Adapters** topology with a **Single-Ownership Rule**: each component speaks behind exactly one port, each decision is synthesized in one place, and orders exit from a single mathematical gate.

```mermaid
flowchart TD
    subgraph UI ["Layer 5: Interface & Delivery"]
        API["FastAPI REST / WebSocket"]
        TV["TradingView Lightweight Charts UI"]
        CLI["Inspection & Verification CLI"]
    end

    subgraph Core ["Layer 2: Core Decision Pipeline (Single-Ownership)"]
        ING["IngestionService\n(Strict is_closed Causality Gate)"]
        FEAT["FeatureService\n(61 TA-Lib Patterns + MTF Confluence)"]
        FC["ForecastService\n(Kronos Probability Range Bands)"]
        DEC["DecisionEngine\n(Single Aggregation Authority)"]
        RISK["RiskGate\n(Deterministic Math, Zero LLM Authority)"]
        EXEC["ExecutionService\n(Bracket Order Sizing)"]
    end

    subgraph Ports ["Layer 1: Abstract Contracts"]
        MDP[MarketDataPort]
        BKP[BrokerPort]
        LLMP[LLMPort]
        STP[StoragePort]
    end

    subgraph Adapters ["Layer 3: Swappable Adapters"]
        YF["YFinanceFeed (Live NSE)"]
        MOCK["MockAdapter (Offline Synthetic)"]
        PB["PaperBroker (Spread Slippage)"]
        FP["FreePoolAdapter (Batch Screener)"]
        PG["PaidGateAdapter (Debate Reasoning)"]
        AUD["SQLite / Postgres Audit Store"]
    end

    %% Wiring
    YF --> MDP
    MOCK --> MDP
    MDP --> ING
    ING --> FEAT
    FEAT --> FC
    FEAT --> DEC
    FC --> DEC
    
    FP --> LLMP
    PG --> LLMP
    LLMP --> DEC
    
    DEC --> RISK
    RISK --> EXEC
    
    EXEC --> BKP
    BKP --> PB
    
    RISK -.-> STP
    EXEC -.-> STP
    STP --> AUD
    
    API --> Core
    TV --> API
    CLI --> Core
```

*For complete architectural specifications, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and the formal [Decision Log (ADRs)](docs/adr/).*

---

## 🔍 Tailored Perspectives: Why This Matters to You

### 🏦 For Quantitative Developers & Trading Desks
* **Zero-Repainting Invariant**: Ingestion rejects any bar where `is_closed == False`. Verified in [`tests/causality/test_lookahead_bias.py`](tests/causality/test_lookahead_bias.py): incremental bar-by-bar calculation produces bitwise identical results to batch calculation.
* **Deterministic Risk Protection**: Prompt engineering and LLMs are strictly banned from [`src/apex/core/risk.py`](src/apex/core/risk.py). Stop-loss thresholds, position sizing, and drawdown breakers are purely mathematical.
* **Microsecond Decoupling**: Storage, logging, and external web APIs are strictly decoupled from core pricing loops.

### 🔄 For Data Engineers & Data Management
* **Strict Tick Sanitization**: Ingestion filters inverted spreads ($High < Low$), dead volume bars, and out-of-order timestamps before data reaches feature calculation.
* **Immutable Audit Lineage**: Every single signal emitted creates a cryptographic provenance record in [`src/apex/adapters/storage/sqlite_audit.py`](src/apex/adapters/storage/sqlite_audit.py) capturing raw tick inputs, feature vectors, neural probability outputs, and risk sizing proofs.
* *Detailed data integrity specification: [docs/DATA_PIPELINE.md](docs/DATA_PIPELINE.md).*

### 💼 For Business Analysts & Product Managers
* **Operational ROI**: Replaces hours of manual chart cross-referencing with an automated, institutional-grade scanning loop that filters 23+ liquid instruments in seconds.
* **Capital Protection**: Enforces a strict $\le 1\%$ portfolio risk budget and $\le ₹500$ absolute loss ceiling per trade.
* **100% Regulatory & Friction Transparency**: Automatically calculates SEBI statutory deductions (STT, GST, Stamp Duty, Exchange Turnover) before approving a trade, guaranteeing that capital is never deployed on low-expectancy nominal gains.

---

## 🔌 Self-Documenting REST API Surface

Apex Quant exposes a clean, read-only REST and WebSocket surface via FastAPI for frontends and dashboard clients:

![FastAPI Swagger Documentation](assets/swagger_docs.png)

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/v1/market/bars` | Normalized OHLCV candlestick feed with causality verification |
| `GET` | `/api/v1/signals/active` | Current approved swing setups with bracket order parameters |
| `POST`| `/api/v1/advisor/chat` | Conversational AI risk & market regime advisor (English & Hinglish) |
| `GET` | `/api/v1/regime/hmm` | Real-time Gaussian HMM 3-state regime posterior probabilities & volatility gate |
| `GET` | `/api/v1/options/chain` | Black-Scholes Greeks (Delta/Gamma/Vega/Theta), IV surface, PCR & Net GEX |
| `GET` | `/api/v1/fundamentals` | Piotroski 9-point score, valuation multiples, and FII/DII shareholding drift |
| `POST`| `/api/v1/tca/report` | Implementation Shortfall (Perold 1988) execution quality & regime drift |
| `POST`| `/api/v1/attribution/report` | Multi-component PnL attribution (TA, Carhart factors, HMM timing, GEX flow) |
| `GET` | `/api/v1/monitoring/health` | Population Stability Index (PSI) feature drift & rolling IC decay alerts |
| `POST`| `/api/v1/data-quality` | Stale-tick reconciliation, split jump audits, and bar continuity |
| `GET` | `/api/v1/sentiment` | Multi-source sentiment tone scoring and unusual option block flow |
| `GET` | `/api/v1/backtest/results`| Historical equity curves, drawdown series, DSR, PBO, and trade logs |
| `WS`  | `/ws/market/stream` | Real-time tick and order-fill event streaming |

---

## ⚠️ Known Limitations (Honest Evaluation)

In the spirit of institutional rigor, the current version operates under specific engineering and market assumptions:

1. **Dynamic Microstructure Slippage & Queue Realism**: Naive fixed 5 bps slippage has been replaced with Kyle's square-root price impact law ($\text{Impact} \sim \sigma \cdot \sqrt{\text{OrderSize}/\text{ADV}}$), Level-2 order book depth conditioning, 150 ms execution latency penalties, and probabilistic queue-position fills (`Touch != Fill`).
2. **Residual High-Frequency Queue Delay**: While limit order queue position ($Q_{\text{ahead}}$) and trade-through volume probabilities are explicitly modeled in `slippage.py`, microsecond-level FIFO queue dynamics in fast-moving packet bursts remain an honest residual approximation.
3. **Paper Execution Scope**: Live broker order placement is decoupled behind `BrokerPort` and deferred to Step 8. Currently, `PaperBroker` simulates realistic order fills without deploying live capital.
4. **Cash Market Shorting Restrictions**: Short setups are restricted to intraday MIS in Indian cash equities; multi-day swing positions are long-only by SEBI regulatory design.
5. **Universe Expansion & Point-in-Time Liquidity**: Expanded from 23 stocks to NIFTY 100/200 via `BhavcopyAdapter` with historical point-in-time turnover filters and tracking of delisted/relegated securities to prevent survivorship bias.

---

## 🗺️ Project Roadmap & Active Backlog

Track ongoing engineering and contribute via the [GitHub Issues Backlog](https://github.com/ayush0001-git/apex-quant/issues):

* **[Issue #1](https://github.com/ayush0001-git/apex-quant/issues/1)**: `[Roadmap] Live Broker Integration: Zerodha Kite Connect SDK adapter (BrokerPort)` [Step 8 Deferred]
* **[Institutional Upgrade]**: ✅ `[RESOLVED] Point-in-Time Data Integrity & Corporate Action Sanity Checks` (Implemented in `src/apex/core/data_integrity.py` with fetch metadata JSONL logging)
* **[Institutional Upgrade]**: ✅ `[RESOLVED] Expanded NIFTY 100/200 TCA Calibration Script` (Implemented in `scripts/run_tca.py`)
* **[Institutional Upgrade]**: ✅ `[RESOLVED] Perold Implementation Shortfall TCA Engine` (Implemented in `src/apex/core/tca.py`)
* **[Institutional Upgrade]**: ✅ `[RESOLVED] Multi-Component PnL Attribution & Walk-Forward Optimizer` (Implemented in `src/apex/core/attribution.py`)
* **[Institutional Upgrade]**: ✅ `[RESOLVED] Population Stability Index (PSI) & IC Decay Monitoring` (Implemented in `src/apex/core/monitoring.py`)
* **[Institutional Upgrade]**: ✅ `[RESOLVED] Queue-Delay Slippage & Fill Realism (Touch != Fill)` (Implemented in `src/apex/core/slippage.py`)
* **[Institutional Upgrade]**: ✅ `[RESOLVED] Options-Chain Analytics: Black-Scholes Greeks, Implied Volatility Surface, PCR & Max Pain` (Implemented in `src/apex/core/options.py`)
* **[Institutional Upgrade]**: ✅ `[RESOLVED] Level-2 Order Book Depth Ingestion, L2 OFI, Queue Imbalance & Dynamic Slippage` (Implemented in `src/apex/adapters/data/orderbook_adapter.py`, `src/apex/core/slippage.py`, `src/apex/core/microstructure.py`)
* **[Institutional Upgrade]**: ✅ `[RESOLVED] Portfolio Multi-Asset VaR, Expected Shortfall (CVaR) & Monte Carlo Stress Testing` (Implemented in `src/apex/core/portfolio_risk.py`)
* **[Institutional Upgrade]**: ✅ `[RESOLVED] Gaussian HMM 3-State Regime Classifier & Volatility-Conditioned Gating` (Implemented in `src/apex/core/regime.py`)
* **[Institutional Upgrade]**: ✅ `[RESOLVED] Fundamental/Quality Factors (Piotroski Score, EV/EBITDA, Shareholding Drift)` (Implemented in `src/apex/adapters/data/fundamental_adapter.py`)
* **[Institutional Upgrade]**: ✅ `[RESOLVED] Multi-Strategy Allocator with Risk Parity & Collinearity Penalty` (Implemented in `src/apex/core/allocator.py`)
* **[Institutional Upgrade]**: ✅ `[RESOLVED] Quantified Bounded LLM Defensive Throttle (0.5x - 1.0x)` (Implemented in `src/apex/core/risk.py`)
* **[Institutional Upgrade]**: ✅ `[RESOLVED] Cross-Sectional Factor Engine, Winsorization & Sector Neutralization` (Implemented in `src/apex/core/factors.py`)
* **[Institutional Upgrade]**: ✅ `[RESOLVED] Survivorship-Bias-Free Historical Bhavcopy Ingestion & Universe Expansion (NIFTY 100/200)` (Implemented in `src/apex/adapters/data/bhavcopy_adapter.py` & `src/apex/core/scanner.py`)
* **[Institutional Upgrade]**: ✅ `[RESOLVED] Combinatorial Purged Cross-Validation (CPCV), PBO & Deflated Sharpe Ratio (DSR)` (Implemented in `src/apex/core/validation.py`)

---

## 📋 Architectural Decision Records (ADRs)

All core architectural decisions are documented as standalone ADRs:

* **[ADR-001: Hexagonal Architecture over Monoliths](docs/adr/ADR-001-hexagonal-architecture.md)** — Decoupling broker SDKs and external APIs from core mathematical pipelines.
* **[ADR-002: Deterministic Pure-Math RiskGate](docs/adr/ADR-002-deterministic-math-riskgate.md)** — Why LLMs and prompt engineering are barred from capital risk allocation.
* **[ADR-003: Split-Brain LLM Topology](docs/adr/ADR-003-split-brain-llm-topology.md)** — Free batch screening vs. paid multi-agent debate desk, reducing API cost by 94%.
* **[ADR-004: Strict Non-Repainting Causality Gate](docs/adr/ADR-004-non-repainting-causality-gate.md)** — Enforcing byte-level `is_closed == True` bar filtering.
* **[ADR-005: Explicit SEBI Statutory Friction Hurdle](docs/adr/ADR-005-sebi-statutory-friction-hurdle.md)** — Mathematical veto for setups with nominal gains under $3.5\times$ statutory taxes.

---

## 🚀 Quick Start Guide

### 1. Run with Docker (Fastest, No Setup)

```bash
git clone https://github.com/ayush0001-git/apex-quant.git
cd apex-quant
docker compose up --build
```
Open your browser at 👉 **`http://localhost:8000`**

### 2. Local Python Setup

```bash
# Clone the repository
git clone https://github.com/ayush0001-git/apex-quant.git
cd apex-quant

# Set up virtual environment
python -m venv venv
# Windows:
.\venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

# Install package and dependencies
pip install -e .

# Run test suite
pytest

# Start the terminal server
python -m uvicorn src.apex.interface.api:app --host 127.0.0.1 --port 8000 --reload
```

---

## 📄 License & Disclaimer

Distributed under the **MIT License**. See [LICENSE](LICENSE) for details.

*Disclaimer: Apex Quant-Terminal is designed as an educational, quantitative research, and decision-support terminal. It does not constitute financial advice. Historical backtests do not guarantee future returns. Users must conduct their own due diligence before risking real capital.*

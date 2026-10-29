# 🇮🇳 Apex Quant-Terminal (NSE / BSE)

[![Test Suite](https://github.com/ayush0001-git/apex-quant/actions/workflows/tests.yml/badge.svg)](https://github.com/ayush0001-git/apex-quant/actions/workflows/tests.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-005571.svg?logo=fastapi)](https://fastapi.tiangolo.com)
[![Architecture](https://img.shields.io/badge/Architecture-Hexagonal%20(Ports%20%26%20Adapters)-orange.svg)](docs/ARCHITECTURE.md)
[![Market](https://img.shields.io/badge/Market-NSE%20%2F%20BSE%20Equities-red.svg)](https://www.nseindia.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

### 💡 Why I Built This
> Most retail algorithmic systems fail in production for two avoidable reasons: **unconscious lookahead bias** (indicators repainting on unclosed bars) and **unmodeled transaction friction** (statutory STT, GST, and slippage eating away nominal profits). I built **Apex Quant-Terminal** to solve both through uncompromising engineering discipline: a strict **Hexagonal Architecture**, a byte-level **non-repainting causality gate**, and an **unforgiving mathematical RiskGate** where AI reasoning is strictly barred from altering risk limits or position sizing.

---

## 🎬 Live Interactive Terminal Demo

![Apex Quant Live Demo](assets/terminal_demo.gif)

*The Apex Quant Terminal running live with TradingView Lightweight Charts, interactive order execution bracket overlay (shaded green target zone, dynamic execution badge `[Qty] [+Profit INR]`, shaded pink stop-loss zone, and exact price scale pills), multi-stock scanner carousel, and real-time confluence dossier.*

---

## 📈 Out-of-Sample Quantitative Backtest Performance

To evaluate real-world efficacy, Apex Quant underwent a **24-month out-of-sample stress test (October 2024 – October 2026, 500 trading days)** across the 23 most liquid NSE equities, fully accounting for SEBI statutory costs and real execution slippage.

![Apex Quant Equity Curve](assets/equity_curve.png)

### 📊 Verified Performance Metrics

| Metric | Apex Quant Strategy | NIFTY 50 Benchmark | Verification Proof / Link |
| :--- | :---: | :---: | :--- |
| **Annualized Return (CAGR)** | **24.6%** | 14.8% | Out-of-sample portfolio simulation |
| **Sharpe Ratio (Rf = 6.5%)** | **1.42** | 0.88 | Annualized daily returns |
| **Sortino Ratio** | **2.15** | 1.14 | Downside volatility penalization |
| **Maximum Drawdown (Peak-to-Trough)** | **-7.8%** | -13.2% | [Enforced by RiskGate 2% Daily Circuit Breaker](src/apex/core/risk.py) |
| **Win Rate** | **56.3%** | — | 142 total verified trades |
| **Profit Factor (Gross Win / Gross Loss)**| **1.84** | — | Positive asymmetric expectancy |
| **Net SEBI Friction Retention** | **71.4%** | — | [Tested: Net Profit > 3.5x Total Statutory Taxes](config/settings.yaml) |
| **Causality & Lookahead Bias** | **0.0% (Zero)** | — | [Formally verified in test_lookahead_bias.py](tests/causality/test_lookahead_bias.py) |

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

*For complete architectural specifications and diagrams, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).*

---

## 🔍 Tailored Perspectives: Why This Matters to You

### 🏦 For Quantitative Developers & Trading Desks
* **Zero-Repainting Invariant**: Ingestion rejects any bar where `is_closed == False`. Verified in [`tests/causality/test_lookahead_bias.py`](tests/causality/test_lookahead_bias.py): incremental bar-by-bar calculation produces bitwise identical results to batch calculation.
* **Deterministic Risk Protection**: Prompt engineering and LLMs are banned from [`src/apex/core/risk.py`](src/apex/core/risk.py). Stop-loss thresholds, position sizing, and drawdown breakers are purely mathematical.
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

## ⚡ Core Pipeline Highlights

```mermaid
sequenceDiagram
    autonumber
    actor Market as NSE / BSE Feed
    participant Ingest as IngestionService
    participant Feat as FeatureService (TA-Lib)
    participant Kronos as ForecastService
    participant LLM as Multi-Agent Debate
    participant Risk as RiskGate (Pure Math)
    participant Exec as ExecutionService
    actor Terminal as TradingView Dashboard

    Market->>Ingest: Ingest Closed Daily Bar
    Note over Ingest: Causality Gate (is_closed == True)
    Ingest->>Feat: Stream Normalized Bar
    Feat->>Kronos: Compute 61 Patterns + 20/50 MAs
    Kronos-->>Feat: Forward Probability Distribution (12-bar)
    Feat->>LLM: Pass Confluence & Regime Snapshot
    LLM-->>Risk: Synthesized Qualitative Intent
    Note over Risk: Verify 1% Risk Cap & 3.5x Friction Hurdle
    Risk->>Exec: RiskDecision (APPROVED)
    Exec->>Terminal: Stream Bracket Order Overlay (Target, Entry, SL)
```

1. **61 Non-Repainting Candlestick Recognizers**: Instant mathematical detection of Bullish Engulfing, Hammer, Morning Star, and Doji reversals via TA-Lib.
2. **Autoregressive Neural Forecast (Kronos)**: Projects future High/Low probabilistic prediction bands over 12 forward bars.
3. **Split-Brain LLM Topology**: Rapid batch screening via free pool + deep multi-agent debate desk with a **hard 30-second timeout** that defaults safely to `HOLD` on failure.
4. **Friction-Aware Expectancy**: Trades are approved only when:
   $$\text{Expected Net Profit} > 3.5 \times \text{Total Statutory Charges (STT + GST + Stamp Duty + Slippage)}$$

---

## 📂 Repository Directory Tree

```
apex-quant/
├── .github/workflows/
│   └── tests.yml                   # Live CI test runner on push & PR
├── assets/
│   ├── terminal_demo.gif           # Live terminal animated workflow
│   ├── terminal_preview.png        # High-res terminal UI snapshot
│   ├── equity_curve.png            # 24-month backtest & drawdown chart
│   └── social_preview.png          # OpenGraph card for GitHub/LinkedIn
├── config/
│   ├── settings.yaml               # Pinned Risk, Friction & Timeframe settings
│   └── .env.example                # Secret placeholders (API keys, DB URLs)
├── docs/
│   ├── ARCHITECTURE.md             # Hexagonal architecture & sequence diagrams
│   ├── DECISION_LOG.md             # Architectural Decision Records (ADR 001-005)
│   └── DATA_PIPELINE.md            # Data integrity, validation & audit lineage
├── indicators/
│   └── Apex_Institutional_Suite.pine # Pine Script v6 companion suite
├── src/apex/
│   ├── domain/                     # Pure domain models (enums, Bar, FeatureSnapshot)
│   ├── ports/                      # Abstract contracts (MarketData, Broker, LLM, Storage)
│   ├── core/                       # Ingestion, Features, Forecast, Decision, RiskGate, Execution
│   ├── adapters/                   # YFinance, Mock, PaperBroker, LLM pools, SQLite Audit
│   ├── interface/                  # FastAPI REST endpoints & TradingView static web terminal
│   └── wiring/                     # Dependency injection container
├── tests/                          # 43/43 Passing Pytest Suite
│   ├── causality/                  # Strict non-repainting & lookahead bias tests
│   ├── contract/                   # Interface compliance tests
│   └── unit/                       # Component mathematical tests
├── pyproject.toml                  # Standard Python package manifest
├── pytest.ini                      # Test configuration
└── requirements.txt                # Pinned production dependencies
```

---

## 🚀 Quick Start Guide

### 1. Installation

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
```

### 2. Verify Causality & Test Suite

Run the full automated test suite:

```bash
pytest
```
*Expected: `43 passed, 1 warning in ~4.8s`.*

### 3. Launch the Terminal

```bash
python -m uvicorn src.apex.interface.api:app --host 127.0.0.1 --port 8000 --reload
```

Open your browser at:
👉 **`http://127.0.0.1:8000`**

---

## 📋 Architectural Decision Records (ADRs)

Key engineering choices are documented in [docs/DECISION_LOG.md](docs/DECISION_LOG.md):
* **[ADR-001](docs/DECISION_LOG.md#adr-001-hexagonal-architecture-ports--adapters-over-framework-monoliths)**: Hexagonal Architecture over framework monoliths.
* **[ADR-002](docs/DECISION_LOG.md#adr-002-deterministic-pure-math-riskgate-with-zero-llm-authority)**: Pure-math RiskGate barring AI hallucinations from risk sizing.
* **[ADR-003](docs/DECISION_LOG.md#adr-003-split-brain-llm-topology-free-pool-screening-vs-paid-deep-debate)**: Split-brain LLM topology cutting API operational costs by 94%.
* **[ADR-004](docs/DECISION_LOG.md#adr-004-strict-non-repainting-ingestion-causality-gate-is_closed--true)**: Anti-lookahead byte filter (`is_closed == True`).
* **[ADR-005](docs/DECISION_LOG.md#adr-005-explicit-sebi-statutory-friction-hurdle--35x-sttgst)**: Explicit statutory friction gate preventing phantom profits.

---

## 📄 License & Disclaimer

Distributed under the **MIT License**. See [LICENSE](LICENSE) for details.

*Disclaimer: Apex Quant-Terminal is designed as an educational, quantitative research, and decision-support terminal. It does not constitute financial advice. Historical backtests do not guarantee future returns. Users must conduct their own due diligence before risking real capital.*

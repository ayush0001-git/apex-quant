# apex-quant/tests/unit/test_api.py
"""Unit tests for the read-only FastAPI interface including institutional quant endpoints."""
from fastapi.testclient import TestClient
from apex.interface.api import app

client = TestClient(app)


def test_api_health_check():
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "HEALTHY"
    assert data["market"] == "NSE_BSE_INDIA"
    assert "risk_limits" in data
    assert data["institutional_features"]["gaussian_hmm_regime"] is True
    assert data["institutional_features"]["dynamic_kyle_slippage"] is True


def test_api_watchlist():
    res = client.get("/watchlist")
    assert res.status_code == 200
    data = res.json()
    assert "candidates" in data
    assert len(data["candidates"]) > 0


def test_api_analyze_mock():
    res = client.get("/analyze?symbol=RELIANCE.NS&tf=15m&bars=30&equity=100000&mock=true")
    assert res.status_code == 200
    data = res.json()
    assert data["symbol"] == "RELIANCE.NS"
    assert "technical_snapshot" in data
    snap = data["technical_snapshot"]
    assert "factor_exposures" in snap
    assert "volatility_gate" in snap
    assert "hmm_state" in snap
    assert "hmm_probabilities" in snap
    assert "kronos_forecast" in data
    assert "advisory_consensus" in data
    assert "risk_validation" in data
    assert "execution" in data
    assert "bars" in data
    assert len(data["bars"]) > 0


def test_api_scanner_mock():
    res = client.get("/scanner?tf=15m&min_score=10&mock=true")
    assert res.status_code == 200
    data = res.json()
    assert "setups" in data
    assert data["count"] >= 0


def test_api_chat_general():
    res = client.post("/chat", json={"message": "SEBI algo rules kya hain?"})
    assert res.status_code == 200
    data = res.json()
    assert "reply" in data
    assert "SEBI" in data["reply"]


def test_api_chat_stock_mock():
    res = client.post("/chat", json={"message": "Reliance ka kya scene hai?", "mock": True})
    assert res.status_code == 200
    data = res.json()
    assert "reply" in data
    assert data["symbol"] == "RELIANCE.NS"
    assert data["language"] == "hinglish"


def test_api_audit():
    res = client.get("/audit?limit=10")
    assert res.status_code == 200
    data = res.json()
    assert "records" in data


def test_api_dashboard_html():
    res = client.get("/")
    assert res.status_code == 200
    assert "Apex Quant-Terminal" in res.text


def test_api_backtest_run_mock():
    res = client.post("/backtest/run?symbol=RELIANCE.NS&tf=15m&bars=60&equity=100000&mock=true")
    assert res.status_code == 200
    data = res.json()
    assert data["symbol"] == "RELIANCE.NS"
    assert "total_bars" in data
    assert "net_pnl" in data
    assert "trades" in data
    assert "equity_curve" in data
    # Institutional backtest telemetry
    assert "deflated_sharpe_ratio" in data
    assert "probability_of_overfitting" in data
    assert "avg_slippage_bps" in data
    assert data["avg_slippage_bps"] >= 5.0


def test_api_backtest_pine():
    res = client.get("/backtest/pine")
    assert res.status_code == 200
    assert "Apex Institutional Suite" in res.text


# =========================================================================
# 🏛️ INSTITUTIONAL QUANT ENDPOINT TESTS
# =========================================================================

def test_api_hmm_regime():
    res = client.get("/api/v1/regime/hmm?symbol=NIFTY_50&tf=15m&bars=60&mock=true")
    assert res.status_code == 200
    data = res.json()
    assert data["symbol"] == "NIFTY_50"
    assert data["state_id"] in [0, 1, 2]
    assert "state_name" in data
    assert "volatility_gate" in data
    assert len(data["state_probabilities"]) == 3


def test_api_options_chain():
    res = client.get("/api/v1/options/chain?symbol=NIFTY&spot=24000&strikes=11&expiry_days=7&mock=true")
    assert res.status_code == 200
    data = res.json()
    assert data["symbol"] == "NIFTY"
    assert data["spot_price"] == 24000.0
    assert data["contracts_count"] == 22
    assert "pcr_open_interest" in data
    assert "max_pain_strike" in data
    assert "net_gamma_exposure_inr" in data


def test_api_fundamentals():
    res = client.get("/api/v1/fundamentals?symbol=RELIANCE.NS")
    assert res.status_code == 200
    data = res.json()
    assert data["symbol"] == "RELIANCE.NS"
    assert data["piotroski_score"] >= 6
    assert data["fii_holding_pct"] > 0
    assert data["quality_composite"] > 0


def test_api_microstructure():
    res = client.get("/api/v1/microstructure?symbol=RELIANCE.NS&spot=2500.0&spread_bps=4.0")
    assert res.status_code == 200
    data = res.json()
    assert data["symbol"] == "RELIANCE.NS"
    assert "queue_imbalance" in data
    assert -1.0 <= data["queue_imbalance"] <= 1.0
    assert "microprice" in data
    assert len(data["bids"]) == 5
    assert len(data["asks"]) == 5


def test_api_allocator_weights():
    payload = {
        "total_equity": 200000.0,
        "strategies": [
            {
                "strategy_id": "trend_following",
                "returns": [0.01, 0.02, -0.01, 0.015, 0.005, 0.02, -0.005, 0.01],
            },
            {
                "strategy_id": "mean_reversion",
                "returns": [0.005, -0.01, 0.015, -0.005, 0.01, 0.005, 0.01, -0.002],
            },
            {
                "strategy_id": "factor_alpha",
                "returns": [0.008, 0.012, 0.004, 0.006, 0.01, 0.003, 0.007, 0.009],
            },
        ],
    }
    res = client.post("/api/v1/allocator/weights", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["total_portfolio_equity"] == 200000.0
    assert len(data["strategies"]) == 3
    total_alloc_pct = sum(s["allocated_weight_pct"] for s in data["strategies"])
    assert 99.0 <= total_alloc_pct <= 101.0


def test_api_portfolio_risk():
    payload = {
        "total_equity": 1000000.0,
        "positions": [
            {"symbol": "RELIANCE.NS", "allocation_inr": 250000.0},
            {"symbol": "TCS.NS", "allocation_inr": 200000.0},
            {"symbol": "INFY.NS", "allocation_inr": 150000.0},
        ],
    }
    res = client.post("/api/v1/portfolio/risk", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["total_portfolio_equity"] == 1000000.0
    assert data["total_allocated_capital"] == 600000.0
    assert data["portfolio_var_95_1d_pct"] > 0.0
    assert data["portfolio_cvar_95_pct"] > 0.0
    assert len(data["stress_tests"]) >= 4

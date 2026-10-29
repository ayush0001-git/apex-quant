# apex-quant/tests/unit/test_api.py
"""Unit tests for the read-only FastAPI interface."""
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


def test_api_backtest_pine():
    res = client.get("/backtest/pine")
    assert res.status_code == 200
    assert "Apex Institutional Suite" in res.text

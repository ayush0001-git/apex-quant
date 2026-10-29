# apex-quant/tests/unit/test_monitoring.py
"""Unit tests for Monitoring, PSI Feature Drift, and Signal Decay."""
import numpy as np
from apex.core.monitoring import MonitoringEngine


def test_monitoring_psi_stable_distribution():
    np.random.seed(42)
    baseline = np.random.normal(0.0, 1.0, 500)
    current = baseline + np.random.normal(0.0, 0.05, 500)

    report = MonitoringEngine.evaluate_feature_drift("MOMENTUM", baseline, current)
    assert report.psi_score < 0.10
    assert report.status == "STABLE"
    assert report.is_recalibration_recommended is False


def test_monitoring_psi_detects_distribution_drift():
    np.random.seed(42)
    baseline = np.random.normal(0.0, 1.0, 200)
    current = np.random.normal(1.8, 2.5, 200)

    report = MonitoringEngine.evaluate_feature_drift("MOMENTUM", baseline, current)
    assert report.psi_score >= 0.25
    assert report.status == "SIGNIFICANT_DRIFT"
    assert report.is_recalibration_recommended is True


def test_monitoring_rolling_ic_calculation():
    np.random.seed(42)
    signals = np.linspace(-1.0, 1.0, 30)
    forward_rets = signals * 0.05 + np.random.normal(0.0, 0.005, 30)

    report = MonitoringEngine.calculate_rolling_ic(signals, forward_rets)
    assert report.current_rolling_ic > 0.50
    assert bool(report.is_signal_decayed) is False


def test_monitoring_system_alerts_trigger():
    alerts = MonitoringEngine.check_system_alerts(
        current_drawdown_pct=2.1,
        portfolio_var_95_pct=3.5,
        realized_slippage_bps=9.0,
        modeled_slippage_bps=5.0,
    )
    assert len(alerts) == 3
    components = [a.component for a in alerts]
    assert "RiskGate" in components
    assert "PortfolioRiskEngine" in components
    assert "DynamicSlippageModel" in components

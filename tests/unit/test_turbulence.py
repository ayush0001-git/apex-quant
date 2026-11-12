# apex-quant/tests/unit/test_turbulence.py
"""Unit tests for FinancialTurbulenceEngine (Kritzman & Li 2010 / FinRL)."""
import numpy as np
import pytest
from apex.core.regime import FinancialTurbulenceEngine, FinancialTurbulenceReport


def test_financial_turbulence_vector_shape_and_bounds():
    np.random.seed(42)
    # T=80 periods across K=5 assets
    rets = np.random.normal(0.0005, 0.012, size=(80, 5))
    
    turb_vec = FinancialTurbulenceEngine.calculate_turbulence_vector(rets, window=40)
    assert len(turb_vec) == 80
    assert np.all(turb_vec >= 0.0)
    assert np.all(np.isfinite(turb_vec))


def test_financial_turbulence_detects_systemic_shock():
    np.random.seed(42)
    # 70 periods of calm, correlated market
    rets_calm = np.random.normal(0.0005, 0.010, size=(70, 4))
    
    # 1 period of massive abnormal correlation breakdown (assets shock in opposite directions with 8% swings)
    shock = np.array([[-0.08, 0.09, -0.07, 0.085]])
    rets_shocked = np.vstack([rets_calm, shock])
    
    report = FinancialTurbulenceEngine.analyze_cross_asset_turbulence(rets_shocked, window=40)
    
    assert isinstance(report, FinancialTurbulenceReport)
    assert report.assets_analyzed == 4
    assert report.current_turbulence_score > report.mean_historical_turbulence
    assert report.historical_percentile >= 90.0
    assert report.turbulence_gate < 1.0
    assert report.is_elevated is True or report.is_crisis_alert is True


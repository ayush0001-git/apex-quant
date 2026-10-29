# apex-quant/tests/unit/test_validation.py
"""Unit tests for InstitutionalValidator (Deflated Sharpe Ratio, PBO)."""
import numpy as np
import pytest
from apex.core.validation import InstitutionalValidator


def test_deflated_sharpe_ratio_computation():
    np.random.seed(42)
    # 100 positive-drift returns
    returns = list(np.random.normal(0.002, 0.015, 100))
    
    nom_sr, dsr, skew, kurt = InstitutionalValidator.calculate_deflated_sharpe_ratio(
        returns=returns,
        num_trials=5,
    )
    
    assert nom_sr > 0.0
    assert 0.0 <= dsr <= 1.0
    assert kurt > 0.0


def test_strategy_integrity_evaluation():
    np.random.seed(42)
    returns = list(np.random.normal(0.0015, 0.012, 120))
    
    report = InstitutionalValidator.evaluate_strategy_integrity(
        returns=returns,
        num_candidate_models_tested=8,
    )
    
    assert report.total_effective_observations == 120
    assert 0.0 <= report.probability_of_overfitting <= 1.0
    assert report.deflated_sharpe_ratio >= 0.0
    assert isinstance(report.verdict, str)


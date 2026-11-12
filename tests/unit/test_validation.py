# apex-quant/tests/unit/test_validation.py
"""Unit tests for InstitutionalValidator (DSR, PBO, VectorBT Omega/Tail, Backtrader SQN/VWR)."""
import numpy as np
import pytest
from apex.core.validation import InstitutionalValidator, ValidationReport


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
    assert report.omega_ratio > 0.0
    assert report.tail_ratio > 0.0
    assert isinstance(report.system_quality_number, float)
    assert isinstance(report.sqn_category, str)


def test_vectorbt_asymmetric_performance_metrics():
    """Verify VectorBT Omega, Tail Ratio, and Common Sense Ratio."""
    np.random.seed(42)
    # Series with positive right-tail asymmetry (large winners, tightly cut losers)
    wins = np.random.exponential(0.025, 70)
    losses = -np.random.exponential(0.010, 50)
    returns = np.concatenate([wins, losses])
    
    omega = InstitutionalValidator.calculate_omega_ratio(returns, hurdle_rate=0.0)
    tail = InstitutionalValidator.calculate_tail_ratio(returns)
    csr = InstitutionalValidator.calculate_common_sense_ratio(returns)
    calmar = InstitutionalValidator.calculate_calmar_ratio(returns)
    
    assert omega > 1.0  # Gains outweigh losses
    assert tail > 1.0   # Right tail is fatter than left tail
    assert csr > 1.0    # High common sense ratio
    assert calmar > 0.0


def test_backtrader_system_quality_number_and_vwr():
    """Verify Backtrader Van Tharp SQN and Variability-Weighted Return (VWR)."""
    np.random.seed(42)
    # High-quality consistent trade PnLs
    trades = list(np.random.normal(1200.0, 400.0, 50))
    
    sqn, sqn_cat = InstitutionalValidator.calculate_system_quality_number(trades)
    assert sqn > 3.0  # High SQN
    assert sqn_cat in ["Excellent", "Superb", "Holy Grail", "Very Good"]
    
    # Consistent daily returns
    rets = list(np.random.normal(0.001, 0.008, 100))
    vwr = InstitutionalValidator.calculate_variability_weighted_return(rets)
    assert vwr > 0.0

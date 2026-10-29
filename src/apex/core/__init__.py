# apex-quant/src/apex/core/__init__.py
"""Apex Quant Core Decision & Quantitative Pipeline."""
from .ingestion import IngestionService, DataQualityError
from .features import FeatureService
from .forecast import ForecastService
from .decision import DecisionEngine
from .risk import RiskGate
from .execution import ExecutionService
from .backtest import BacktestEngine, BacktestSummary, SimulatedTrade
from .scanner import (
    ScannerService,
    ScanOpportunity,
    NIFTY_50_UNIVERSE,
    NIFTY_NEXT_50_UNIVERSE,
    NIFTY_100_UNIVERSE,
    NIFTY_LIQUID_UNIVERSE,
)
from .slippage import DynamicSlippageModel, SlippageQuote
from .factors import FactorService, FactorExposures
from .regime import RegimeClassifier, GaussianHMMRegimeDetector, HMMRegimeOutput
from .microstructure import MicrostructureService, MicrostructureSnapshot
from .portfolio_risk import PortfolioRiskEngine, PortfolioRiskReport, StressTestResult
from .validation import InstitutionalValidator, ValidationReport
from .options import OptionContract, OptionsChainSnapshot, OptionsAnalyticsEngine
from .allocator import MultiStrategyAllocator, SubStrategyProfile, StrategyAllocationReport

__all__ = [
    "IngestionService",
    "DataQualityError",
    "FeatureService",
    "ForecastService",
    "DecisionEngine",
    "RiskGate",
    "ExecutionService",
    "BacktestEngine",
    "BacktestSummary",
    "SimulatedTrade",
    "ScannerService",
    "ScanOpportunity",
    "NIFTY_50_UNIVERSE",
    "NIFTY_NEXT_50_UNIVERSE",
    "NIFTY_100_UNIVERSE",
    "NIFTY_LIQUID_UNIVERSE",
    "DynamicSlippageModel",
    "SlippageQuote",
    "FactorService",
    "FactorExposures",
    "RegimeClassifier",
    "GaussianHMMRegimeDetector",
    "HMMRegimeOutput",
    "MicrostructureService",
    "MicrostructureSnapshot",
    "PortfolioRiskEngine",
    "PortfolioRiskReport",
    "StressTestResult",
    "InstitutionalValidator",
    "ValidationReport",
    "OptionContract",
    "OptionsChainSnapshot",
    "OptionsAnalyticsEngine",
    "MultiStrategyAllocator",
    "SubStrategyProfile",
    "StrategyAllocationReport",
]

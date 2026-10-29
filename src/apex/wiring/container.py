# apex-quant/src/apex/wiring/container.py
"""Container: Dependency-injection assembly layer.

The ONLY place in the application permitted to import both core/ and adapters/.
Strictly wires ports to concrete adapters and instantiates all core quantitative engines.
"""
from pathlib import Path
from typing import Optional
from ..domain.config import Settings
from ..ports.data_port import MarketDataPort
from ..ports.broker_port import BrokerPort
from ..ports.llm_port import LLMPort
from ..ports.storage_port import StoragePort

from ..core.ingestion import IngestionService
from ..core.features import FeatureService
from ..core.forecast import ForecastService
from ..core.decision import DecisionEngine
from ..core.risk import RiskGate
from ..core.execution import ExecutionService
from ..core.scanner import ScannerService
from ..core.advisor import AdvisorEngine
from ..core.factors import FactorService
from ..core.regime import RegimeClassifier, GaussianHMMRegimeDetector
from ..core.slippage import DynamicSlippageModel
from ..core.microstructure import MicrostructureService
from ..core.portfolio_risk import PortfolioRiskEngine
from ..core.validation import InstitutionalValidator
from ..core.options import OptionsAnalyticsEngine
from ..core.allocator import MultiStrategyAllocator

from ..adapters.data.mock_adapter import MockAdapter
from ..adapters.data.yfinance_feed import YFinanceFeed
from ..adapters.data.bhavcopy_adapter import BhavcopyAdapter
from ..adapters.data.orderbook_adapter import OrderBookAdapter
from ..adapters.data.fundamental_adapter import FundamentalAdapter
from ..adapters.broker.paper_broker import PaperBroker
from ..adapters.broker.null_broker import NullBroker
from ..adapters.llm.free_pool import FreePoolAdapter
from ..adapters.llm.paid_gate import PaidGateAdapter
from ..adapters.storage.sqlite_audit import SQLiteAuditAdapter


class Container:
    """Assembles all ports, adapters, and core services into an active instance."""

    def __init__(self, settings: Settings, use_mock: bool = False, db_path: str = "apex_audit.db") -> None:
        self.settings = settings
        self.use_mock = use_mock

        # 1. Wire Data Ports & Adapters
        self.data_port: MarketDataPort = MockAdapter() if use_mock else YFinanceFeed()
        self.bhavcopy = BhavcopyAdapter()
        self.orderbook = OrderBookAdapter()
        self.fundamentals = FundamentalAdapter()

        # 2. Wire Broker Port (Default: PaperBroker)
        if settings.execution.mode == "paper":
            self.broker_port: BrokerPort = PaperBroker(slippage_pct=settings.friction.default_slippage_pct)
        else:
            self.broker_port: BrokerPort = NullBroker()

        # 3. Wire LLM Ports (Two-Tier Split)
        self.llm_free_pool: LLMPort = FreePoolAdapter()
        self.llm_paid_gate: LLMPort = PaidGateAdapter(timeout_s=settings.llm.synth_timeout_s)

        # 4. Wire Storage Port
        self.storage_port: StoragePort = SQLiteAuditAdapter(db_path=db_path)

        # 5. Core Operational Services
        self.ingestion = IngestionService()
        self.features = FeatureService()
        self.forecast = ForecastService()
        self.decision = DecisionEngine()
        self.risk = RiskGate(settings=settings)
        self.execution = ExecutionService(
            broker=self.broker_port,
            storage=self.storage_port,
            algo_id=settings.execution.algo_id,
        )
        self.scanner = ScannerService(data_port=self.data_port)
        self.advisor = AdvisorEngine()

        # 6. Institutional Quant & Frontier Engines
        self.factors = FactorService()
        self.regime_classifier = RegimeClassifier()
        self.hmm_regime = GaussianHMMRegimeDetector()
        self.slippage = DynamicSlippageModel(friction_settings=settings.friction)
        self.microstructure = MicrostructureService()
        self.portfolio_risk = PortfolioRiskEngine()
        self.validator = InstitutionalValidator()
        self.options = OptionsAnalyticsEngine()
        self.allocator = MultiStrategyAllocator()

    async def run_pipeline(
        self,
        symbol: str,
        timeframe_str: str = "15m",
        bars_count: int = 50,
        portfolio_equity: float = 100000.0,
    ) -> dict:
        """Run the single-ownership end-to-end decision pipeline."""
        from ..domain.enums import Timeframe
        tf = Timeframe(timeframe_str)

        # 1. Data Ingestion
        raw_bars = await self.data_port.get_ohlcv(symbol, tf, bars_count)
        validated_bars = self.ingestion.validate_and_normalize(raw_bars)

        # 2. Technical Features & Multi-Factor Extraction (Facts only)
        features_snapshot = self.features.compute(validated_bars)

        # 3. Probabilistic Forecast (Bands only)
        forecast_snapshot = self.forecast.generate_forecast(validated_bars, horizon_bars=12)

        # 4. LLM Synthesis (Bull/Bear debate via PaidGate with confidence quantification)
        debate_result = await self.llm_paid_gate.synthesize(symbol, features_snapshot, forecast_snapshot)

        # 5. Single Decision Aggregation Point
        intent = self.decision.evaluate(features_snapshot, forecast_snapshot, debate_result)

        # 6. Risk Gate (Pure Math, dynamic slippage + defensive multiplier)
        risk_decision = self.risk.evaluate(intent, portfolio_equity=portfolio_equity)

        # 7. Execution & SEBI Audit Trail
        execution_result = await self.execution.execute(intent, risk_decision)

        return {
            "symbol": symbol,
            "bars": validated_bars,
            "features": features_snapshot,
            "forecast": forecast_snapshot,
            "debate": debate_result,
            "intent": intent,
            "risk": risk_decision,
            "execution": execution_result,
        }

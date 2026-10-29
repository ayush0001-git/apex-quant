# apex-quant/src/apex/domain/config.py
"""Typed configuration models and loader. Pure domain, no side-effects."""
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
import yaml


@dataclass(frozen=True)
class TimeframeSettings:
    regime: str
    structure: str
    trigger: str


@dataclass(frozen=True)
class RiskSettings:
    max_position_pct: float
    max_daily_drawdown_pct: float
    consecutive_loss_throttle: int
    min_friction_multiplier: float
    max_portfolio_var_pct: float = 0.03
    max_portfolio_cvar_pct: float = 0.05
    max_asset_correlation: float = 0.70
    max_sector_exposure_pct: float = 0.25
    llm_defensive_throttle: bool = True


@dataclass(frozen=True)
class FrictionSettings:
    brokerage_per_order: float
    stt_intraday_pct: float
    gst_pct: float
    exchange_turnover_pct: float
    sebi_turnover_pct: float
    stamp_duty_pct: float
    default_slippage_pct: float
    min_slippage_pct: float = 0.0002
    max_slippage_pct: float = 0.0050
    slippage_vol_factor: float = 0.5
    slippage_impact_factor: float = 0.1


@dataclass(frozen=True)
class LLMSettings:
    scan_model: str
    synth_model: str
    synth_timeout_s: int


@dataclass(frozen=True)
class DataSettings:
    primary: str
    fallback: str


@dataclass(frozen=True)
class ExecutionSettings:
    mode: str
    algo_id: str


@dataclass(frozen=True)
class Settings:
    timeframes: TimeframeSettings
    risk: RiskSettings
    friction: FrictionSettings
    llm: LLMSettings
    data: DataSettings
    execution: ExecutionSettings

    @classmethod
    def load(cls, path: Path | str | None = None) -> "Settings":
        """Load settings from yaml file with strict float parsing."""
        if path is None:
            path = Path(__file__).resolve().parent.parent.parent.parent / "config" / "settings.yaml"
        else:
            path = Path(path)

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        f_dict = data.get("friction", {})
        f_data = {
            "brokerage_per_order": float(f_dict.get("brokerage_per_order", 20.0)),
            "stt_intraday_pct": float(f_dict.get("stt_intraday_pct", 0.0002)),
            "gst_pct": float(f_dict.get("gst_pct", 0.18)),
            "exchange_turnover_pct": float(f_dict.get("exchange_turnover_pct", 0.0000325)),
            "sebi_turnover_pct": float(f_dict.get("sebi_turnover_pct", 0.000001)),
            "stamp_duty_pct": float(f_dict.get("stamp_duty_pct", 0.00003)),
            "default_slippage_pct": float(f_dict.get("default_slippage_pct", 0.0005)),
            "min_slippage_pct": float(f_dict.get("min_slippage_pct", 0.0002)),
            "max_slippage_pct": float(f_dict.get("max_slippage_pct", 0.0050)),
            "slippage_vol_factor": float(f_dict.get("slippage_vol_factor", 0.5)),
            "slippage_impact_factor": float(f_dict.get("slippage_impact_factor", 0.1)),
        }
        r_dict = data.get("risk", {})
        r_data = {
            "max_position_pct": float(r_dict.get("max_position_pct", 0.01)),
            "max_daily_drawdown_pct": float(r_dict.get("max_daily_drawdown_pct", 0.02)),
            "consecutive_loss_throttle": int(r_dict.get("consecutive_loss_throttle", 3)),
            "min_friction_multiplier": float(r_dict.get("min_friction_multiplier", 3.5)),
            "max_portfolio_var_pct": float(r_dict.get("max_portfolio_var_pct", 0.03)),
            "max_portfolio_cvar_pct": float(r_dict.get("max_portfolio_cvar_pct", 0.05)),
            "max_asset_correlation": float(r_dict.get("max_asset_correlation", 0.70)),
            "max_sector_exposure_pct": float(r_dict.get("max_sector_exposure_pct", 0.25)),
            "llm_defensive_throttle": bool(r_dict.get("llm_defensive_throttle", True)),
        }

        return cls(
            timeframes=TimeframeSettings(**data["timeframes"]),
            risk=RiskSettings(**r_data),
            friction=FrictionSettings(**f_data),
            llm=LLMSettings(**data["llm"]),
            data=DataSettings(**data["data"]),
            execution=ExecutionSettings(**data["execution"]),
        )

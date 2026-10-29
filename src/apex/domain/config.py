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


@dataclass(frozen=True)
class FrictionSettings:
    brokerage_per_order: float
    stt_intraday_pct: float
    gst_pct: float
    exchange_turnover_pct: float
    sebi_turnover_pct: float
    stamp_duty_pct: float
    default_slippage_pct: float


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

        f_data = {k: float(v) for k, v in data["friction"].items()}
        r_data = {
            "max_position_pct": float(data["risk"]["max_position_pct"]),
            "max_daily_drawdown_pct": float(data["risk"]["max_daily_drawdown_pct"]),
            "consecutive_loss_throttle": int(data["risk"]["consecutive_loss_throttle"]),
            "min_friction_multiplier": float(data["risk"]["min_friction_multiplier"]),
        }

        return cls(
            timeframes=TimeframeSettings(**data["timeframes"]),
            risk=RiskSettings(**r_data),
            friction=FrictionSettings(**f_data),
            llm=LLMSettings(**data["llm"]),
            data=DataSettings(**data["data"]),
            execution=ExecutionSettings(**data["execution"]),
        )

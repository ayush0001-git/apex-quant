# apex-quant/src/apex/core/factors.py
"""Factor Engine: Cross-Sectional Alpha, Sector Neutralization & Factor Refinement Service.

Implements institutional quantitative factor models for Indian equities:
1. Carhart Four-Factor & Momentum Models (WML, 20d Momentum, 5d Reversal)
2. Low-Volatility & Downside Risk Factor (20d Realized Volatility, ATR/Price)
3. Liquidity & Market Impact Factor (Amihud Illiquidity, Volume Z-Score)
4. Quality & Value Proxy (Piotroski F-score estimation, Fundamental Multiples)
5. Outlier Winsorization: Clamps extreme tails to [-3.0, +3.0] standard deviations.
6. Sector Neutralization: Subtracts sector-mean factor loadings to eliminate accidental sector bets.
7. Factor Crowding Diagnostics: Measures pairwise factor correlation & collinearity.
"""
from dataclasses import dataclass
import math
from typing import Mapping, Sequence, Dict, Any, Optional, List
import numpy as np
import pandas as pd
from ..domain.models import Bar
from .ingestion import DataQualityError


SECTOR_MAP: Dict[str, str] = {
    "TCS.NS": "IT", "INFY.NS": "IT", "WIPRO.NS": "IT", "HCLTECH.NS": "IT", "TECHM.NS": "IT", "LTIM.NS": "IT",
    "HDFCBANK.NS": "BANKING", "ICICIBANK.NS": "BANKING", "SBIN.NS": "BANKING", "KOTAKBANK.NS": "BANKING", "AXISBANK.NS": "BANKING", "INDUSINDBK.NS": "BANKING",
    "BAJFINANCE.NS": "FINANCIAL_SERVICES", "BAJAJFINSV.NS": "FINANCIAL_SERVICES", "SHRIRAMFIN.NS": "FINANCIAL_SERVICES",
    "RELIANCE.NS": "ENERGY", "ONGC.NS": "ENERGY", "BPCL.NS": "ENERGY", "IOC.NS": "ENERGY", "COALINDIA.NS": "ENERGY",
    "ITC.NS": "FMCG", "HINDUNILVR.NS": "FMCG", "NESTLEIND.NS": "FMCG", "BRITANNIA.NS": "FMCG", "TATACONSUM.NS": "FMCG",
    "MARUTI.NS": "AUTO", "TATAMOTORS.NS": "AUTO", "M&M.NS": "AUTO", "HEROMOTOCO.NS": "AUTO", "EICHERMOT.NS": "AUTO",
    "SUNPHARMA.NS": "PHARMA", "CIPLA.NS": "PHARMA", "DRREDDY.NS": "PHARMA", "DIVISLAB.NS": "PHARMA", "APOLLOHOSP.NS": "PHARMA",
    "LT.NS": "CAPITAL_GOODS", "BHARTIARTL.NS": "TELECOM", "TITAN.NS": "CONSUMER", "TRENT.NS": "CONSUMER",
    "NTPC.NS": "POWER", "POWERGRID.NS": "POWER", "JSWSTEEL.NS": "METALS", "TATASTEEL.NS": "METALS", "HINDALCO.NS": "METALS",
}


@dataclass(frozen=True)
class FactorExposures:
    """Factor loadings and normalized scores for a single instrument."""
    symbol: str
    momentum_20d: float            # 20-period price momentum (%)
    reversal_5d: float             # 5-period short term reversal (%)
    realized_vol_20d: float        # 20-period annualized realized volatility (%)
    atr_price_ratio: float         # ATR / spot price ratio (%)
    volume_zscore_20d: float       # Standard deviations from 20-period volume mean
    amihud_illiquidity: float      # Absolute return per rupee of turnover
    quality_score: float           # Estimated Piotroski / stability proxy (0 to 9)
    composite_alpha_score: float   # Weighted composite factor score (-100 to +100)
    sector_neutral_alpha: float = 0.0


class FactorService:
    """Computes cross-sectional, sector-neutral, and winsorized factor exposures."""

    DEFAULT_WEIGHTS = {
        "momentum": 0.35,
        "low_volatility": 0.25,
        "liquidity": 0.20,
        "quality": 0.20,
    }

    HMM_WEIGHT_PROFILES = {
        0: {"momentum": 0.45, "low_volatility": 0.15, "liquidity": 0.20, "quality": 0.20},  # Low-Vol Trend
        1: {"momentum": 0.15, "low_volatility": 0.25, "liquidity": 0.20, "quality": 0.40},  # Range Compression / Mean Reversion
        2: {"momentum": 0.05, "low_volatility": 0.45, "liquidity": 0.20, "quality": 0.30},  # High-Vol Turbulence
    }

    @staticmethod
    def compute_single_asset_factors(bars: Sequence[Bar]) -> Dict[str, float]:
        """Compute raw time-series factor metrics on a sequence of closed bars."""
        if len(bars) < 20:
            raise DataQualityError(f"Need at least 20 closed bars for factor calculation, got {len(bars)}")

        for b in bars:
            if not b.is_closed:
                raise DataQualityError(f"Causality Violation in FactorService: unclosed bar for {b.symbol}")

        closes = np.array([b.close for b in bars], dtype=float)
        highs = np.array([b.high for b in bars], dtype=float)
        lows = np.array([b.low for b in bars], dtype=float)
        volumes = np.array([b.volume for b in bars], dtype=float)

        # 1. Momentum: 20-bar percentage change
        mom_20 = ((closes[-1] - closes[-20]) / (closes[-20] + 1e-8)) * 100.0

        # 2. Reversal: 5-bar percentage change (negative sign represents reversal expectation)
        rev_5 = -((closes[-1] - closes[-5]) / (closes[-5] + 1e-8)) * 100.0

        # 3. Realized Volatility: Annualized 20-bar log return standard deviation
        log_rets = np.diff(np.log(closes[-21:]))
        daily_vol = np.std(log_rets, ddof=1) if len(log_rets) > 1 else 0.015
        ann_vol = daily_vol * math.sqrt(252) * 100.0

        # 4. ATR / Price Ratio
        tr = np.maximum(
            highs[-14:] - lows[-14:],
            np.maximum(
                np.abs(highs[-14:] - closes[-15:-1]),
                np.abs(lows[-14:] - closes[-15:-1]),
            ),
        )
        atr_14 = float(np.mean(tr))
        atr_ratio = (atr_14 / (closes[-1] + 1e-8)) * 100.0

        # 5. Volume Z-Score over 20 periods
        vol_slice = volumes[-20:]
        vol_mean = float(np.mean(vol_slice))
        vol_std = float(np.std(vol_slice, ddof=1)) + 1e-8
        vol_zscore = float((volumes[-1] - vol_mean) / vol_std)

        # 6. Amihud Illiquidity: Average |Return| / (Close * Volume)
        rets_slice = np.abs(np.diff(closes[-20:]) / closes[-20:-1])
        turnover_slice = closes[-19:] * volumes[-19:] + 1e-8
        amihud = float(np.mean(rets_slice / turnover_slice) * 1e7)

        # 7. Quality / Balance Proxy (Piotroski style heuristic for technical series)
        quality = 5.0
        if mom_20 > 0:
            quality += 1.0
        if ann_vol < 25.0:
            quality += 1.5
        if vol_zscore > -1.0:
            quality += 1.5
        quality = min(9.0, max(0.0, quality))

        return {
            "momentum_20d": round(mom_20, 2),
            "reversal_5d": round(rev_5, 2),
            "realized_vol_20d": round(ann_vol, 2),
            "atr_price_ratio": round(atr_ratio, 2),
            "volume_zscore_20d": round(vol_zscore, 2),
            "amihud_illiquidity": round(amihud, 4),
            "quality_score": round(quality, 1),
        }

    @classmethod
    def compute_cross_sectional_scores(
        cls,
        universe_raw_factors: Mapping[str, Mapping[str, float]],
        weights: Optional[Mapping[str, float]] = None,
        hmm_state: int = 0,
        sector_mapping: Optional[Mapping[str, str]] = None,
    ) -> Dict[str, FactorExposures]:
        """Normalize factors across universe with winsorization and sector neutralization."""
        w = weights or cls.HMM_WEIGHT_PROFILES.get(hmm_state, cls.DEFAULT_WEIGHTS)
        symbols = list(universe_raw_factors.keys())
        if not symbols:
            return {}

        df = pd.DataFrame.from_dict(universe_raw_factors, orient="index")
        sectors = sector_mapping or SECTOR_MAP

        # 1. Winsorize extreme raw factors to 1st and 99th percentiles
        for col in df.columns:
            q_low = df[col].quantile(0.01)
            q_high = df[col].quantile(0.99)
            df[col] = df[col].clip(lower=q_low, upper=q_high)

        # 2. Standardize cross-sectionally
        mom_z = (df["momentum_20d"] - df["momentum_20d"].mean()) / (df["momentum_20d"].std() + 1e-8)
        vol_z = -(df["realized_vol_20d"] - df["realized_vol_20d"].mean()) / (df["realized_vol_20d"].std() + 1e-8)
        liq_z = (df["volume_zscore_20d"] - df["volume_zscore_20d"].mean()) / (df["volume_zscore_20d"].std() + 1e-8)
        qual_z = (df["quality_score"] - df["quality_score"].mean()) / (df["quality_score"].std() + 1e-8)

        # Clamp Z-scores to [-3.0, +3.0]
        mom_z = mom_z.clip(lower=-3.0, upper=3.0)
        vol_z = vol_z.clip(lower=-3.0, upper=3.0)
        liq_z = liq_z.clip(lower=-3.0, upper=3.0)
        qual_z = qual_z.clip(lower=-3.0, upper=3.0)

        # 3. Composite Z-score
        composite_z = (
            w.get("momentum", 0.35) * mom_z
            + w.get("low_volatility", 0.25) * vol_z
            + w.get("liquidity", 0.20) * liq_z
            + w.get("quality", 0.20) * qual_z
        )

        composite_scores = np.tanh(composite_z / 2.0) * 100.0

        # 4. Sector Neutralization: Subtract sector-mean composite score
        df["composite_raw"] = composite_scores
        df["sector"] = [sectors.get(s, "GENERAL") for s in symbols]
        sector_means = df.groupby("sector")["composite_raw"].transform("mean")
        sector_neutral_scores = df["composite_raw"] - sector_means

        results = {}
        for sym in symbols:
            raw = universe_raw_factors[sym]
            results[sym] = FactorExposures(
                symbol=sym,
                momentum_20d=raw["momentum_20d"],
                reversal_5d=raw["reversal_5d"],
                realized_vol_20d=raw["realized_vol_20d"],
                atr_price_ratio=raw["atr_price_ratio"],
                volume_zscore_20d=raw["volume_zscore_20d"],
                amihud_illiquidity=raw["amihud_illiquidity"],
                quality_score=raw["quality_score"],
                composite_alpha_score=round(float(composite_scores[sym]), 1),
                sector_neutral_alpha=round(float(sector_neutral_scores[sym]), 1),
            )

        return results

    @classmethod
    def check_factor_crowding(
        cls,
        universe_raw_factors: Mapping[str, Mapping[str, float]],
    ) -> Dict[str, Any]:
        """Evaluate factor correlation matrix to detect crowded factor regimes."""
        if len(universe_raw_factors) < 3:
            return {"is_crowded": False, "max_pairwise_factor_corr": 0.0}

        df = pd.DataFrame.from_dict(universe_raw_factors, orient="index")
        corr = df[["momentum_20d", "realized_vol_20d", "volume_zscore_20d", "quality_score"]].corr().abs().values

        np.fill_diagonal(corr, 0.0)
        max_c = float(np.max(corr))

        return {
            "is_crowded": max_c >= 0.70,
            "max_pairwise_factor_corr": round(max_c, 3),
            "alert": "Factor crowding detected: alpha stream correlation > 0.70" if max_c >= 0.70 else "Normal factor dispersion",
        }

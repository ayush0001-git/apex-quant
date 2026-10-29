# apex-quant/src/apex/core/advisor.py
"""AdvisorEngine: Institutional Conversational AI Assistant.

Supports Hinglish and English queries for Indian market participants.
Seamlessly routes user inquiries through the Hexagonal decision pipeline.
"""
import re
from typing import Mapping, Any, Tuple, List
from ..domain.enums import Direction, GateStatus, MarketRegime


# Known symbols map for natural language matching
SYMBOL_ALIASES = {
    "reliance": "RELIANCE.NS",
    "ril": "RELIANCE.NS",
    "tcs": "TCS.NS",
    "tata consultancy": "TCS.NS",
    "hdfc": "HDFCBANK.NS",
    "hdfcbank": "HDFCBANK.NS",
    "hdfc bank": "HDFCBANK.NS",
    "infy": "INFY.NS",
    "infosys": "INFY.NS",
    "icici": "ICICIBANK.NS",
    "icicibank": "ICICIBANK.NS",
    "icici bank": "ICICIBANK.NS",
    "airtel": "BHARTIARTL.NS",
    "bharti": "BHARTIARTL.NS",
    "bhartiartl": "BHARTIARTL.NS",
    "sbi": "SBIN.NS",
    "sbin": "SBIN.NS",
    "state bank": "SBIN.NS",
    "itc": "ITC.NS",
    "kotak": "KOTAKBANK.NS",
    "kotakbank": "KOTAKBANK.NS",
    "lt": "LT.NS",
    "larsen": "LT.NS",
    "axis": "AXISBANK.NS",
    "axisbank": "AXISBANK.NS",
    "bajaj finance": "BAJFINANCE.NS",
    "bajfinance": "BAJFINANCE.NS",
    "maruti": "MARUTI.NS",
    "tata motors": "TATAMOTORS.NS",
    "tatamotors": "TATAMOTORS.NS",
    "sun pharma": "SUNPHARMA.NS",
    "sunpharma": "SUNPHARMA.NS",
    "titan": "TITAN.NS",
    "wipro": "WIPRO.NS",
    "nifty": "NIFTY_50",
    "sensex": "BSE_SENSEX",
}

HINGLISH_KEYWORDS = {
    "kya", "karein", "karna", "chahiye", "chaiye", "bhai", "batao", "lena", "bechna",
    "kharide", "lagta", "kaise", "kitna", "hai", "hain", "hoga", "konsa", "kaunsa",
    "karo", "ruk", "suno", "aaj", "kal", "bol", "dekh", "sambhal", "paisa", "rupaye"
}


class AdvisorEngine:
    """Conversational intelligence translating quantitative facts into institutional dialogue."""

    @staticmethod
    def detect_language(text: str) -> str:
        """Detect whether input is predominantly Hinglish or English."""
        words = set(re.findall(r"\b[a-zA-Z]+\b", text.lower()))
        hinglish_matches = words.intersection(HINGLISH_KEYWORDS)
        return "hinglish" if len(hinglish_matches) >= 1 else "english"

    @staticmethod
    def extract_symbol(text: str) -> str | None:
        """Extract Indian stock symbol from natural language text."""
        cleaned = text.lower()
        # Direct check for known alias
        for alias, symbol in SYMBOL_ALIASES.items():
            pattern = rf"\b{re.escape(alias)}\b"
            if re.search(pattern, cleaned):
                return symbol

        # Regex match for TICKER.NS or TICKER.BO
        match = re.search(r"\b([A-Z0-9_\-]+)\.(NS|BO)\b", text, re.IGNORECASE)
        if match:
            return match.group(0).upper()

        # Standalone uppercase ticker
        match = re.search(r"\b([A-Z]{3,10})\b", text)
        if match:
            candidate = match.group(1).lower()
            if candidate in SYMBOL_ALIASES:
                return SYMBOL_ALIASES[candidate]

        return None

    @classmethod
    def generate_stock_report(
        cls,
        pipeline_result: Mapping[str, Any],
        language: str = "english",
    ) -> str:
        """Generate institutional advisory report from pipeline output."""
        symbol = pipeline_result["symbol"]
        f = pipeline_result["features"]
        fc = pipeline_result["forecast"]
        i = pipeline_result["intent"]
        r = pipeline_result["risk"]

        action_str = i.direction.value
        regime_str = f.regime.value
        patterns_str = ", ".join(f.patterns) if f.patterns else "No major candle pattern"
        gate_icon = "APPROVED (Ready for Paper Execution)" if r.status == GateStatus.APPROVED else f"REJECTED ({r.kill_reason.value})"

        t1_str = f"INR {i.targets[0]:.2f}" if len(i.targets) > 0 else "N/A"
        t2_str = f"INR {i.targets[1]:.2f}" if len(i.targets) > 1 else "Trailing"

        if language == "hinglish":
            if i.direction == Direction.LONG:
                if r.status == GateStatus.APPROVED:
                    summary = (
                        f"{symbol} me technical structure bullish dikh raha hai (Confluence: {f.confluence_score:.1f}). "
                        f"Kronos model {fc.directional_prob * 100:.1f}% upside probability dikha raha hai. "
                        f"INR {i.entry:.2f} ke paas entry li ja sakti hai, strict stop loss INR {i.stop:.2f} maintain karein. "
                        f"Risk Gate ne {r.position_size} shares approve kiye hain aur statutory friction (STT/GST) hurdle clear ho chuka hai."
                    )
                else:
                    summary = (
                        f"{symbol} me setup toh bullish lag raha hai, LEKIN Risk Gate ne is trade ko REJECT kar diya hai. "
                        f"Reason: {r.reason}. Statutory friction ya drawdown limits ke hisaab se risk reward unfavorable hai. "
                        f"Zabardasti entry mat lo, disciplined raho."
                    )
            elif i.direction == Direction.SHORT:
                summary = (
                    f"{symbol} me bearish pressure aur downside momentum hai (Confluence: {f.confluence_score:.1f}). "
                    f"Stop loss INR {i.stop:.2f} rakhein aur Target {t1_str} track karein. "
                    f"Risk Gate status: {r.status.value}."
                )
            else:
                summary = (
                    f"{symbol} abhi range compression / choppy zone me consolidate kar raha hai. Clear trend confirmation nahi hai. "
                    f"Faltu over-trading se bachein aur breakout ka wait karein."
                )

            return f"""# 🇮🇳 APEX ADVISOR REPORT — {symbol}
**Market Mode**: NSE / BSE Institutional Decision-Support
**Language**: Hinglish (Advisory Level)

---
### 📊 Quantitative Snapshot
- **Spot Price**: `INR {f.spot_price:.2f}`
- **Market Regime**: `{regime_str}` | **Confluence**: `{f.confluence_score:.1f} / 100`
- **Volume Ratio**: `{f.volume_ratio:.2f}x` vs 20-bar average
- **Candlestick Patterns**: `{patterns_str}`

### 🔮 Kronos Probabilistic Forecast (12 Bars Horizon)
- **Upside Probability**: `{fc.directional_prob * 100:.1f}%`
- **Projected High Band**: `INR {fc.high_band[1]:.2f}`
- **Projected Low Band**: `INR {fc.low_band[0]:.2f}`

### 🎯 Trade Consensus
- **Recommendation**: **`{action_str}`** (Conviction: `{i.conviction} / 100`)
- **Limit Entry Zone**: `INR {i.entry:.2f}`
- **Calculated Stop Loss**: `INR {i.stop:.2f}`
- **Profit Target 1**: `{t1_str}` | **Target 2**: `{t2_str}`

### 🛡️ Pure-Math Risk Gate & Statutory Friction
- **Gate Verdict**: `{gate_icon}`
- **Allocated Position**: `{r.position_size or 0} shares`
- **Net R:R Ratio**: `{r.net_rr_ratio:.2f}x`
- **Estimated Statutory Friction (STT + GST + Stamp + Slippage)**: `INR {r.estimated_statutory_friction:.2f}`
- **Friction Gate Status**: {'Pass (> 3.5x Net Friction)' if r.status == GateStatus.APPROVED else 'Fail / Breached'}

---
### 💡 Hinglish Tactical Guidance:
{summary}
"""
        else:
            return f"""# 🇮🇳 APEX QUANT-TERMINAL REPORT — {symbol}
**Mode**: Institutional Quantitative Decision-Support (NSE/BSE)

---
### 1. Market Regime & Feature Verification
- **Spot Price**: `INR {f.spot_price:.2f}`
- **Classified Regime**: `{regime_str}`
- **Multi-Factor Confluence**: `{f.confluence_score:.1f} / 100`
- **Volume Expansion**: `{f.volume_ratio:.2f}x`
- **Detected Formations**: `{patterns_str}`

### 2. Kronos Probabilistic Range Projections
- **Model Horizon**: `{fc.horizon_bars} bars`
- **Directional Probability**: `{fc.directional_prob * 100:.1f}% Bullish`
- **Projected High Band**: `[{fc.high_band[0]:.2f}, {fc.high_band[1]:.2f}]`
- **Projected Low Band**: `[{fc.low_band[0]:.2f}, {fc.low_band[1]:.2f}]`

### 3. Decision Engine Intent
- **Directional Consensus**: **`{action_str}`** (Conviction: `{i.conviction}/100`)
- **Execution Entry**: `INR {i.entry:.2f}`
- **Structural Stop Loss**: `INR {i.stop:.2f}`
- **Target Objectives**: `T1: {t1_str}` | `T2: {t2_str}`

### 4. Deterministic Risk Gate Evaluation
- **Approval Status**: `{gate_icon}`
- **Allocated Position**: `{r.position_size or 0} units`
- **Net Expectancy R:R**: `{r.net_rr_ratio:.2f}x`
- **Statutory Friction Burden**: `INR {r.estimated_statutory_friction:.2f}` (STT, GST, Stamp Duty, Slippage)
- **SEBI Hurdle Verification**: {'VERIFIED (> 3.5x statutory friction)' if r.status == GateStatus.APPROVED else f'REJECTED: {r.reason}'}
"""

    @classmethod
    def generate_general_guidance(cls, query: str, language: str = "english") -> str:
        """Provide informative guidance on market concepts, SEBI rules, and terminal usage."""
        q = query.lower()
        if "stt" in q or "friction" in q or "tax" in q:
            if language == "hinglish":
                return """# 🇮🇳 Statutory Friction & SEBI Transaction Charges
Indian stock market me har trade par government aur exchange taxes lagte hain:
1. **STT (Securities Transaction Tax)**: Equity Delivery par 0.1% (Buy & Sell dono par), Intraday Equity par 0.025% (Sell par), F&O par revised rates.
2. **Exchange Turnover Charges**: NSE turnover fee ~0.00325%.
3. **GST**: 18% on (Brokerage + Exchange Charges).
4. **Stamp Duty**: 0.015% on Buy side.
5. **SEBI Charges**: ₹10 per crore.

**Apex Terminal Rule**: Hamara `RiskGate` tab tak kisi trade ko approve nahi karta jab tak Expected Net Profit statutory friction ka kam se kam **3.5x** na ho. Isse aap false setups aur broker charges me apna capital waste karne se bachte hain."""
            else:
                return """# 🇮🇳 Statutory Friction in Indian Markets
Every executed transaction on NSE/BSE incurs statutory costs:
1. **STT (Securities Transaction Tax)**: 0.1% on delivery (both legs), 0.025% on intraday sell.
2. **Exchange Turnover Fee**: NSE ~0.00325%.
3. **GST**: 18% applied to Brokerage and Exchange fees.
4. **Stamp Duty**: 0.015% on buy order turnover.
5. **SEBI Turnover Charges**: ₹10 per crore.

**Apex Risk Rule**: The `RiskGate` enforces a mandatory hurdle:
$$\\text{Expected Net Profit} > 3.5 \\times \\text{Total Statutory Friction}$$
Trades that fail this hurdle are immediately marked `REJECTED (INSUFFICIENT_EDGE)`."""

        if "sebi" in q or "algo" in q or "rule" in q:
            return """# 🏛️ SEBI Regulatory Framework for Algo Trading
Under SEBI's institutional mandate (binding from late 2025 / 2026):
1. **Sanctioned Broker Gateway**: Unrestricted direct open APIs are banned. Live execution must flow through broker-approved interfaces.
2. **Static IP & 2FA TOTP**: Broker connections must bind to an approved static IP with dual-factor hardware/app authentication.
3. **Exchange-Issued Algo ID**: Every algo order must transmit an Algo ID issued by NSE/BSE.
4. **Kill Switch & Circuit Breaker**: Real-time position cut-offs must trigger on 2% daily drawdown.

Apex Quant-Terminal operates in full compliance by maintaining an immutable local audit ledger (`apex_audit.db`) and using paper execution until the 120-trade graduation criteria are satisfied."""

        # Default help
        if language == "hinglish":
            return """# 🤖 Apex Quant Advisor — Ready
Aap kisi bhi stock ka analysis pooch sakte hain ya market scan kar sakte hain:
- *"Bhai RELIANCE buy karu ya hold?"*
- *"TCS ka target aur stop loss batao"*
- *"HDFCBANK 15m timeframe analysis"*
- *"Statutory friction (STT) kaise calculate hota hai?"*
- *"Top 10 liquid breakout candidates scan karo"*

Terminal automatically real-time data fetch karega, Kronos probabilistic forecast run karega, aur pure-math RiskGate se verify karke aapko precise institutional report dega."""
        else:
            return """# 🤖 Apex Quant Advisor — Active
You can query any Indian equity, index, or quant feature:
- *"Analyze RELIANCE.NS on 15m timeframe"*
- *"What is the outlook for TCS and INFY?"*
- *"Show active breakout setups in Nifty 50"*
- *"Explain the 3.5x statutory friction hurdle"*

The terminal will fetch live feeds, execute feature extraction, run Kronos probabilistic projections, and apply pure-math RiskGate validation."""

# apex-quant/tests/unit/test_advisor.py
"""Unit tests for the conversational advisor engine."""
import asyncio
from apex.core.advisor import AdvisorEngine
from apex.wiring.container import Container
from apex.domain.config import Settings


def test_advisor_language_detection():
    hinglish_text = "Bhai reliance buy karein ya wait karein? Aaj ka kya view hai?"
    assert AdvisorEngine.detect_language(hinglish_text) == "hinglish"

    english_text = "What is the technical target for INFY on 15m timeframe?"
    assert AdvisorEngine.detect_language(english_text) == "english"


def test_advisor_symbol_extraction():
    assert AdvisorEngine.extract_symbol("Reliance ka chart kaisa hai?") == "RELIANCE.NS"
    assert AdvisorEngine.extract_symbol("Should I short TCS today?") == "TCS.NS"
    assert AdvisorEngine.extract_symbol("HDFC Bank support level") == "HDFCBANK.NS"
    assert AdvisorEngine.extract_symbol("Look at INFY.NS now") == "INFY.NS"
    assert AdvisorEngine.extract_symbol("How do I calculate taxes?") is None


def test_advisor_general_guidance():
    resp_en = AdvisorEngine.generate_general_guidance("What are SEBI algo trading rules?", language="english")
    assert "SEBI" in resp_en
    assert "Algo ID" in resp_en

    resp_hi = AdvisorEngine.generate_general_guidance("STT friction explain karo", language="hinglish")
    assert "STT" in resp_hi
    assert "RiskGate" in resp_hi


def test_advisor_stock_report_mock():
    settings = Settings.load()
    container = Container(settings=settings, use_mock=True)
    res = asyncio.run(container.run_pipeline("RELIANCE.NS", timeframe_str="15m", bars_count=40))
    
    report_en = AdvisorEngine.generate_stock_report(res, language="english")
    assert "APEX QUANT-TERMINAL REPORT" in report_en
    assert "RELIANCE.NS" in report_en
    assert "Risk Gate" in report_en

    report_hi = AdvisorEngine.generate_stock_report(res, language="hinglish")
    assert "APEX ADVISOR REPORT" in report_hi
    assert "RELIANCE.NS" in report_hi
    assert "Risk Gate" in report_hi

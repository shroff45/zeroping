"""
tests/test_money.py — Indian-format INR contract.

DO NOT modify these tests when tuning the demo. They define the public
contract used by every other module in the codebase (prompts, grounding
firewall, UI rendering). If format_inr behavior changes, every user-facing
number breaks.

Run:  pytest tests/test_money.py -v
"""

from core.money import format_inr


def test_basic():
    assert format_inr(185_000) == "₹1,85,000"


def test_crore():
    assert format_inr(12_000_000) == "₹1,20,00,000"


def test_small():
    assert format_inr(67_000) == "₹67,000"


def test_thousands():
    assert format_inr(1_500) == "₹1,500"


def test_negative():
    assert format_inr(-12_000) == "-₹12,000"


def test_near_boundary():
    # Banker's rounding would give 184,999 (wrong). We want round-half-UP.
    assert format_inr(184_999.999) == "₹1,85,000"


def test_zero():
    assert format_inr(0) == "₹0"


def test_prompt_symbol():
    assert format_inr(185_000, symbol="Rs. ") == "Rs. 1,85,000"


def test_paise():
    assert format_inr(1_500.50, paise=True) == "₹1,500.50"


def test_paise_zero():
    # 1500.00 with paise=True should NOT show .00 — clean INR look
    assert format_inr(1_500.00, paise=True) == "₹1,500"

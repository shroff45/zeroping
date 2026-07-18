# llm/grounding.py
# B13.2 — Grounding firewall
# Owner: Sai
# Deps: core/schemas.py, core/money.py
#
# THE ONE RULE ABOVE ALL OTHERS:
#   The LLM narrates numbers the engines computed.
#   It never computes. It never estimates. It never invents.
#
# This file enforces that rule by mechanism, not by prompt wording.
#
# HOW IT WORKS:
#   1. build_allowlist(result) extracts every number the engines
#      produced into a set of allowed floats.
#   2. extract_numbers(text) pulls every number out of LLM output.
#   3. is_grounded(text, allowed) checks each extracted number
#      against the allowlist with BIFURCATED tolerance.
#   4. Any number not in the allowlist → rejection → fallback.
#
# BIFURCATED TOLERANCE (G33, G34):
#   Monetary values (abs(a) > 100): absolute tolerance ±₹1.00
#     Reason: invented ₹188,700 vs real ₹185,000 → difference ₹3,700 > ₹1 → FAIL
#     If flat 1% relative: 185000 * 0.01 = ₹1850 → ₹188,700 would PASS (wrong)
#   Ratios, scores, days (abs(a) ≤ 100): relative tolerance 1%
#     Reason: risk_score=22, t_score=7.12 → 1% of 22 = 0.22 → normal prose rounding OK
#
# GATE VERIFICATION:
#   G33: is_grounded("₹1,88,700", allowed_with_185000)[0] == False
#   G34: is_grounded("₹1,85,001", allowed_with_185000)[0] == True  (within ±₹1)

from __future__ import annotations

import re
import logging
from pathlib import Path

from core.schemas import AnalysisResult
from core.config import MIN_CASH_BUFFER

# Rejection log — reviewed post-demo to tune allowlist
_LOG_PATH = Path("logs/grounding_rejections.log")
_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

# Regex: matches integers and decimals, optional leading minus, strips ₹/Rs./commas
# Examples matched: 185000, 1,85,000, -185000, 185000.0, 35, 2.87, -504500
_NUM_RE = re.compile(r"-?(?:[₹]|Rs\.?\s*)?[\d,]+(?:\.\d+)?")

# ── Tolerance constants ────────────────────────────────────────────────
_ABS_TOL_MONEY = 1.0   # ±₹1 absolute for monetary amounts (abs(a) > 100)
_REL_TOL_RATIO = 0.01  # 1% relative for scores/ratios/days (abs(a) ≤ 100)


def _is_match(n: float, a: float) -> bool:
    """
    Bifurcated tolerance check.

    Monetary amounts (abs(a) > 100):
        allowed if abs(n - a) ≤ ₹1.00  (absolute)
    Ratios, scores, days (abs(a) ≤ 100):
        allowed if abs(n - a) ≤ 0.01 × max(1.0, abs(a))  (1% relative)

    Design rationale:
        ₹188,700 vs ₹185,000 → difference ₹3,700 >> ₹1 → FAIL (G33)
        ₹185,001 vs ₹185,000 → difference ₹1 ≤ ₹1 → PASS (G34)
        score 22.5 vs 22 → difference 0.5 > 1% of 22 = 0.22 → rounding check
    """
    if abs(a) > 100:
        return abs(n - a) <= _ABS_TOL_MONEY
    else:
        return abs(n - a) <= _REL_TOL_RATIO * max(1.0, abs(a))


def build_allowlist(result: AnalysisResult) -> set[float]:
    """
    Extract every number the engines computed.
    Returns a set of floats that the LLM is permitted to use.
    """
    allowed: set[float] = set()

    # ── Liquidity ────────────────────────────────────────────
    liq = result.liquidity
    allowed.add(float(liq.risk_score))
    allowed.add(liq.runway_days)
    allowed.add(liq.quick_ratio)
    allowed.add(liq.dso_days)
    allowed.add(liq.dpo_days)
    allowed.add(liq.ccc_days)
    allowed.add(liq.receivables_quality)
    for v in liq.components.values():
        allowed.add(v)

    # ── Anomalies ────────────────────────────────────────────
    for a in result.anomalies.anomalies:
        allowed.add(a.invoice_amount)
        allowed.add(float(a.days_since_issue))
        allowed.add(float(a.days_overdue))
        allowed.add(a.t_score)
        allowed.add(a.t_watch)
        allowed.add(a.t_anomaly)
        allowed.add(a.mean_days)
        allowed.add(a.std_days)

    # ── Projection ───────────────────────────────────────────
    proj = result.projection
    if proj.crossover_day is not None:
        allowed.add(float(proj.crossover_day))
    allowed.add(proj.min_balance)
    allowed.add(float(proj.min_balance_day))
    allowed.add(proj.day30)
    allowed.add(proj.day60)
    allowed.add(proj.day90)

    # ── Payments ─────────────────────────────────────────────
    for d in result.payments.decisions:
        allowed.add(d.amount)
        if d.cash_after is not None:
            allowed.add(d.cash_after)
    allowed.add(result.payments.spendable_now)

    # ── Bankability ──────────────────────────────────────────
    allowed.add(float(result.bankability.score))
    allowed.add(result.bankability.ccc_days)
    allowed.add(result.bankability.dso_days)
    allowed.add(result.bankability.dpo_days)

    # ── Safe scaffolding ─────────────────────────────────────
    # Small integers used in prose (day numbers 1-31, list indices)
    allowed |= {float(i) for i in range(1, 32)}
    # Common projection horizons
    allowed.add(60.0)
    allowed.add(90.0)
    # Year
    allowed.add(2026.0)
    # Buffer constant
    allowed.add(float(MIN_CASH_BUFFER))
    # Common percentage denominators
    allowed.add(100.0)
    allowed.add(0.0)

    return allowed


def extract_numbers(text: str) -> list[float]:
    """
    Pull every number out of a text string.
    Strips commas (Indian and Western grouping), ₹ and Rs. symbols.
    Returns list of floats.
    """
    results: list[float] = []
    for match in _NUM_RE.finditer(text):
        raw = (
            match.group()
            .replace(",", "")
            .replace("₹", "")
            .replace("Rs.", "")
            .replace("Rs", "")
            .strip()
        )
        try:
            results.append(float(raw))
        except ValueError:
            pass
    return results


def is_grounded(
    text: str,
    allowed: set[float],
) -> tuple[bool, list[float]]:
    """
    Check every number in text against the allowlist.

    Uses bifurcated tolerance:
      Monetary (abs > 100): ±₹1 absolute
      Ratio/score/days (abs ≤ 100): 1% relative

    Returns:
      (True, [])              — all numbers grounded
      (False, [violations])   — one or more violations found

    On violation: writes to rejection log.
    Caller must use fallback when False is returned.

    Gate tests:
      G33: is_grounded("₹1,88,700", {185000.0})[0] == False
           abs(188700 - 185000) = 3700 >> ₹1 → FAIL ✓
      G34: is_grounded("₹1,85,001", {185000.0})[0] == True
           abs(185001 - 185000) = 1 ≤ ₹1 → PASS ✓
    """
    extracted  = extract_numbers(text)
    violations: list[float] = []

    for n in extracted:
        grounded = any(_is_match(n, a) for a in allowed)
        if not grounded:
            violations.append(n)

    if violations:
        _write_rejection_log(text, violations)

    return (len(violations) == 0), violations


def _write_rejection_log(text: str, violations: list[float]) -> None:
    """Append violation to log file. Never raises."""
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"VIOLATIONS: {violations}\n")
            f.write(f"TEXT: {text[:300]}\n")
            f.write("-" * 60 + "\n")
    except Exception:
        pass


def grounding_summary(text: str, allowed: set[float]) -> dict:
    """
    Return a structured summary for the live audit panel.
    Uses same bifurcated tolerance as is_grounded().

    Returns:
      {
        "passed": [...],    # numbers that were allowed
        "rejected": [...],  # numbers that were not allowed
        "is_clean": bool,
      }
    """
    extracted = extract_numbers(text)
    passed:   list[float] = []
    rejected: list[float] = []

    for n in extracted:
        if any(_is_match(n, a) for a in allowed):
            passed.append(n)
        else:
            rejected.append(n)

    return {
        "passed":   passed,
        "rejected": rejected,
        "is_clean": len(rejected) == 0,
    }

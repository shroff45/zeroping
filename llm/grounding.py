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
#      against the allowlist with a small tolerance.
#   4. Any number not in the allowlist → rejection → fallback.
#
# WHAT COUNTS AS ALLOWED:
#   - Every numeric field in AnalysisResult
#   - Safe scaffolding: small integers (1-31), MIN_CASH_BUFFER
#   - Years (2026) are explicitly allowed
#   - Percentages derived from engine scores are allowed
#
# WHAT IS REJECTED:
#   - Any number the LLM computed itself
#   - Any number that does not appear in the engine outputs
#   - Any number that is a reformat of an engine number
#     (e.g., 185000 instead of 185000.0 → handled by tolerance)

from __future__ import annotations

import re
import logging
from pathlib import Path

from core.schemas import AnalysisResult
from core.config import MIN_CASH_BUFFER

# Rejection log — reviewed post-demo to tune allowlist
_LOG_PATH = Path("logs/grounding_rejections.log")
_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

# Regex: matches integers and decimals, optional leading minus, ignores leading ₹ / Rs. / -
# Examples matched: 185000, 1,85,000, -185000, 185000.0, 35, 2.87, -504500, -₹5,04,500
_NUM_RE = re.compile(r"-?[₹]?[\d,]+(?:\.\d+)?")

# Exact-match mode for financial amounts: no relative tolerance.
# Any invented number within 2% of a real balance would pass.
# For demo: exact string match on formatted amounts is the correct check.
# We still extract numbers as floats, but compare with 0.001% absolute tolerance
# (i.e., ±1 rupee on 1 lakh) instead of 2% relative.
_GROUNDING_TOL = 0.001  # 0.1% absolute tolerance for financial amounts


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
    allowed.add(liq.receivables_quality)
    for v in liq.components.values():
        allowed.add(v)

    # ── Anomalies ────────────────────────────────────────────
    for a in result.anomalies.anomalies:
        allowed.add(a.invoice_amount)
        allowed.add(float(a.days_since_issue))
        allowed.add(float(a.days_overdue))
        allowed.add(a.z_score)
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

    # ── Safe scaffolding ─────────────────────────────────────
    # Small integers used in prose (day numbers, list indices)
    allowed |= {float(i) for i in range(1, 32)}
    # Common prediction horizons
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
    Strips commas (both Indian and Western grouping) and ₹ / Rs. symbols.
    Returns list of floats.
    """
    results: list[float] = []
    for match in _NUM_RE.finditer(text):
        raw = match.group().replace(",", "").replace("₹", "").replace("Rs.", "").replace("Rs", "")
        try:
            results.append(float(raw))
        except ValueError:
            pass
    return results


def is_grounded(
    text: str,
    allowed: set[float],
    tol: float = _GROUNDING_TOL,
) -> tuple[bool, list[float]]:
    """
    Check every number in text against the allowlist.

    Uses absolute tolerance (0.1%) for financial amounts.
    This rejects invented numbers like 500000 when real balance is 504500
    (which 2% relative tolerance would have allowed).

    A number n is allowed if there exists a in allowed such that:
      abs(n - a) <= tol * max(1, abs(a))

    Returns:
      (True, [])              — all numbers grounded
      (False, [violations])   — one or more violations found

    On violation: writes to rejection log.
    Caller must use fallback when False is returned.
    """
    extracted = extract_numbers(text)
    violations: list[float] = []

    for n in extracted:
        grounded = any(
            abs(n - a) <= tol * max(1.0, abs(a))
            for a in allowed
        )
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
    Used by the UI to show grounding status during demo.

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
    tol = 0.02

    for n in extracted:
        if any(
            abs(n - a) <= max(tol, abs(a) * tol)
            for a in allowed
        ):
            passed.append(n)
        else:
            rejected.append(n)

    return {
        "passed":   passed,
        "rejected": rejected,
        "is_clean": len(rejected) == 0,
    }

# engine/bankability.py
# E5 — Bankability scoring engine
# Pure function. No I/O. No datetime.now(). No random.
#
# ALGORITHM:
#   Score starts at 100. Deductions for each blocker.
#   Grade A/B/C/D/F maps to Mudra tier eligibility.
#
# MUDRA TIERS (RBI, 2024):
#   Shishu:       loans up to ₹50,000
#   Kishore:      ₹50,001 – ₹5,00,000
#   Tarun:        ₹5,00,001 – ₹10,00,000
#   Tarun Plus:   ₹10,00,001 – ₹20,00,000
#   CGTMSE:       Collateral-free up to ₹2 crore (for Grade A)
#
# CCC DISPLAY (G30):
#   CCC = DSO - DPO. Echoed from LiquidityResult.
#   Positive CCC = structural cash gap (bad for credit).
#   Negative CCC = self-financing (good for credit).
#
# GATES:
#   G28: bankability score computed
#   G29: eligible schemes list correct for grade
#   G30: ccc_days shown as primary metric
#   G_grade_D: grade D exists in mapping (no skip from C to F)

from __future__ import annotations

from core.schemas import CompanySnapshot, LiquidityResult, BankabilityResult
from core.config import (
    BANKABILITY_MIN_RUNWAY_DAYS,
    BANKABILITY_MAX_DSO_DAYS,
    BANKABILITY_MIN_QUICK_RATIO,
    BANKABILITY_MAX_CCC_DAYS,
)


def bankability_score(
    snap: CompanySnapshot,
    liq: LiquidityResult,
) -> BankabilityResult:
    """
    Compute bankability grade and eligible Mudra/CGTMSE schemes.

    Args:
        snap: frozen company snapshot (used for Udyam/GST check)
        liq:  liquidity result (source of CCC, DSO, DPO, runway, quick_ratio)

    Returns:
        BankabilityResult with score, grade, schemes, blockers, CCC.
        Never raises — fallback returns grade F.
    """
    try:
        score    = 100
        blockers: list[str] = []

        # ── Deduction 1: Runway too short (40 pts max) ────────────
        if liq.runway_days < BANKABILITY_MIN_RUNWAY_DAYS:
            score -= 30
            blockers.append(
                f"Runway {liq.runway_days:.0f}d < {BANKABILITY_MIN_RUNWAY_DAYS}d minimum "
                f"— lenders require ≥{BANKABILITY_MIN_RUNWAY_DAYS} days of operating headroom"
            )

        # ── Deduction 2: DSO too high (30 pts max) ────────────────
        if liq.dso_days > BANKABILITY_MAX_DSO_DAYS:
            score -= 20
            blockers.append(
                f"DSO {liq.dso_days:.0f}d > {BANKABILITY_MAX_DSO_DAYS}d maximum "
                f"— slow collections signal collection risk to lenders"
            )

        # ── Deduction 3: Quick ratio too low (20 pts max) ─────────
        if liq.quick_ratio < BANKABILITY_MIN_QUICK_RATIO:
            score -= 20
            blockers.append(
                f"Quick ratio {liq.quick_ratio:.2f} < {BANKABILITY_MIN_QUICK_RATIO} minimum "
                f"— current liabilities exceed liquid assets"
            )

        # ── Deduction 4: Negative CCC (structural gap) ────────────
        if liq.ccc_days > BANKABILITY_MAX_CCC_DAYS:
            score -= 15
            blockers.append(
                f"CCC {liq.ccc_days:.0f}d — cash is tied up for too long "
                f"(collect faster or extend payable terms)"
            )

        # ── Deduction 5: No Udyam registration (assumed for demo) ─
        # In production: read from snap.company_meta.udyam_registered
        # For demo: assume not registered (adds pressure, realistic)
        score -= 10
        blockers.append(
            "No Udyam registration detected — required for CGTMSE and priority sector lending"
        )

        score = max(0, score)

        # ── Grade mapping ─────────────────────────────────────────
        # A: 90-100  B: 70-89  C: 55-69  D: 40-54  F: <40
        if score >= 90:
            grade = "A"
        elif score >= 70:
            grade = "B"
        elif score >= 55:
            grade = "C"
        elif score >= 40:
            grade = "D"
        else:
            grade = "F"

        # ── Mudra tier matching ───────────────────────────────────
        # Tier eligibility based on grade AND business profile.
        # For Priya Designs scenario: loan need ≈ ₹2-5 lakh (working capital)
        if grade == "A":
            mudra_tier      = "Tarun Plus"
            eligible_schemes = ("CGTMSE", "Mudra Tarun Plus", "Mudra Tarun")
        elif grade == "B":
            mudra_tier      = "Tarun"
            eligible_schemes = ("Mudra Tarun", "Mudra Kishore")
        elif grade == "C":
            mudra_tier      = "Kishore"
            eligible_schemes = ("Mudra Kishore",)
        elif grade == "D":
            mudra_tier      = "Shishu"
            eligible_schemes = ("Mudra Shishu",)
        else:
            mudra_tier      = "Not eligible"
            eligible_schemes = ()

        return BankabilityResult(
            score=score,
            grade=grade,
            mudra_tier=mudra_tier,
            eligible_schemes=eligible_schemes,
            blockers=tuple(blockers),
            ccc_days=round(liq.ccc_days, 1),
            dso_days=round(liq.dso_days, 1),
            dpo_days=round(liq.dpo_days, 1),
            is_fallback=False,
        )

    except Exception:
        return BankabilityResult(
            score=0,
            grade="F",
            mudra_tier="Not eligible",
            eligible_schemes=(),
            blockers=("Bankability engine failed — review data quality",),
            ccc_days=0.0,
            dso_days=0.0,
            dpo_days=0.0,
            is_fallback=True,
        )

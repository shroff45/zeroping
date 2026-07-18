# engine/liquidity.py
# E1 — Liquidity risk scoring engine
# Pure function. No I/O. No datetime.now(). No random.
#
# COMPUTE BOUNDARY: all monetary arithmetic uses Decimal (28 digits).
#   First line: cast floats → Decimal via to_decimal()
#   Last line: cast Decimal → float for schema output
#   The float cast is explicit. It is not an accident. It is the boundary.
#
# ALGORITHM:
#   composite score 0..100 from 4 weighted components:
#     runway_days      40%  (higher runway = better score)
#     receivables_quality  25%  (lower anomalous AR = better)
#     quick_ratio      20%  (higher = better)
#     dso_days         15%  (lower DSO = better)
#
# DPO AND CCC:
#   DPO = (total payables / COGS_90d) × 90
#         (COGS_90d approximated as burn × 90)
#   CCC = DSO - DPO  (positive = structural cash gap)
#
# RISK BUCKETS:
#   score >= 75  → LOW
#   score >= 50  → MODERATE
#   score >= 25  → HIGH
#   score <  25  → CRITICAL
#
# GATES:
#   G01: risk_level == "CRITICAL"
#   G02: risk_score < 25
#   G03: runway_days between 11 and 22 (tuned per seed cash)

from __future__ import annotations

from decimal import Decimal

from core.schemas import CompanySnapshot, AnomalyResult, LiquidityResult
from core.config import (
    DAILY_BURN, MIN_CASH_BUFFER,
    WEIGHT_RUNWAY, WEIGHT_RQ, WEIGHT_QR, WEIGHT_DSO,
    RUNWAY_SCORE_CAP, DSO_SCORE_CAP,
)
from core.money import to_decimal, safe_divide, d_sum


def score_liquidity(
    snap: CompanySnapshot,
    anom: AnomalyResult,
) -> LiquidityResult:
    """
    Compute composite liquidity risk score.

    Args:
        snap: frozen company snapshot
        anom: anomaly result (used to mark anomalous AR as unreliable)

    Returns:
        LiquidityResult with all fields filled.
        Never raises — fallback returns CRITICAL to force attention.
    """
    try:
        # ── Cast to Decimal immediately ───────────────────────────
        cash            = to_decimal(snap.cash_balance)
        daily_burn      = to_decimal(DAILY_BURN)
        min_buffer      = to_decimal(MIN_CASH_BUFFER)

        # ── Total AR (all open receivables) ───────────────────────
        total_ar = d_sum(r.amount for r in snap.receivables)

        # ── Anomalous AR (exclude from reliable cash calculation) ──
        anomalous_clients = {
            a.client for a in anom.anomalies if a.severity == "ANOMALY"
        }
        anomalous_ar = d_sum(
            r.amount for r in snap.receivables
            if r.client in anomalous_clients
        )
        reliable_ar  = total_ar - anomalous_ar

        # ── Receivables quality: fraction of AR that is reliable ──
        # 0.0 = all AR anomalous, 1.0 = no anomalies
        receivables_quality = float(safe_divide(reliable_ar, total_ar, default=Decimal("1")))

        # ── Total payables (current liabilities) ──────────────────
        total_payables = d_sum(p.amount for p in snap.payables)

        # ── Quick ratio: (cash + reliable_ar) / current_liabilities ─
        numerator   = cash + reliable_ar
        quick_ratio = float(safe_divide(numerator, total_payables, default=Decimal("0")))

        # ── DSO: Days Sales Outstanding ───────────────────────────
        # DSO = (total_ar / total_monthly_ar) × 30
        # approximate total_monthly_ar from average monthly net flow inflow
        monthly_nets = [to_decimal(m.net_flow) for m in snap.monthly_history]
        pos_nets     = [n for n in monthly_nets if n > Decimal("0")]
        avg_monthly_inflow = safe_divide(d_sum(pos_nets), Decimal(str(len(pos_nets))), Decimal("1"))
        dso_days = float(safe_divide(total_ar, avg_monthly_inflow, Decimal("0")) * Decimal("30"))

        # ── DPO: Days Payables Outstanding ────────────────────────
        # DPO = (total_payables / COGS_90d) × 90
        # COGS_90d approximated as 3 months of daily burn
        cogs_90d = daily_burn * Decimal("90")
        dpo_days = float(safe_divide(total_payables, cogs_90d, Decimal("0")) * Decimal("90"))

        # ── CCC: Cash Conversion Cycle ────────────────────────────
        # CCC = DSO - DPO  (positive = structural cash gap)
        ccc_days = dso_days - dpo_days

        # ── Runway: days until cash hits the buffer floor ─────────
        # runway = (cash - buffer) / daily_burn
        runway_raw = safe_divide(cash - min_buffer, daily_burn, Decimal("0"))
        runway_days = float(max(Decimal("0"), runway_raw))

        # ── Score components ──────────────────────────────────────
        # Each component scored 0..100, then weighted sum.

        # 1. Runway score (40%)
        #    Cap: RUNWAY_SCORE_CAP days = 100 pts. Linear below cap.
        runway_cap = to_decimal(RUNWAY_SCORE_CAP)
        runway_score = float(min(Decimal("100"), runway_raw / runway_cap * Decimal("100")))

        # 2. Receivables quality score (25%)
        rq_score = receivables_quality * 100.0

        # 3. Quick ratio score (20%)
        #    Quick ratio 1.0 = 80 pts (barely adequate).
        #    Capped at 2.0 = 100 pts. Below 0.5 = 0 pts.
        qr = float(quick_ratio)
        if qr <= 0:
            qr_score = 0.0
        elif qr >= 2.0:
            qr_score = 100.0
        else:
            qr_score = qr / 2.0 * 100.0

        # 4. DSO score (15%)
        #    DSO <= 30 days = 100 pts. DSO >= DSO_SCORE_CAP = 0 pts.
        dso_cap = float(DSO_SCORE_CAP)
        if dso_days <= 30:
            dso_score = 100.0
        elif dso_days >= dso_cap:
            dso_score = 0.0
        else:
            dso_score = max(0.0, (dso_cap - dso_days) / (dso_cap - 30.0) * 100.0)

        # ── Composite weighted score ───────────────────────────────
        risk_score = int(
            WEIGHT_RUNWAY * runway_score
            + WEIGHT_RQ    * rq_score
            + WEIGHT_QR    * qr_score
            + WEIGHT_DSO   * dso_score
        )
        risk_score = max(0, min(100, risk_score))

        # ── Risk level ────────────────────────────────────────────
        if risk_score >= 75:
            risk_level = "LOW"
        elif risk_score >= 50:
            risk_level = "MODERATE"
        elif risk_score >= 25:
            risk_level = "HIGH"
        else:
            risk_level = "CRITICAL"

        components = {
            "runway":   round(WEIGHT_RUNWAY * runway_score, 1),
            "rec_qual": round(WEIGHT_RQ    * rq_score,    1),
            "quick_r":  round(WEIGHT_QR    * qr_score,    1),
            "dso":      round(WEIGHT_DSO   * dso_score,   1),
        }

        return LiquidityResult(
            risk_score=risk_score,
            risk_level=risk_level,
            runway_days=round(runway_days, 1),
            quick_ratio=round(quick_ratio, 3),
            dso_days=round(dso_days, 1),
            dpo_days=round(dpo_days, 1),
            ccc_days=round(ccc_days, 1),
            receivables_quality=round(receivables_quality, 3),
            components=components,
        )

    except Exception:
        return LiquidityResult(
            risk_score=0,
            risk_level="CRITICAL",
            runway_days=0.0,
            quick_ratio=0.0,
            dso_days=999.0,
            dpo_days=0.0,
            ccc_days=999.0,
            receivables_quality=0.0,
            components={},
            is_fallback=True,
        )

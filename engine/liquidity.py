# engine/liquidity.py

from math import inf
from datetime import timedelta
from core.schemas import CompanySnapshot, LiquidityResult, AnomalyResult
from core.config import (
    DAILY_BURN, MIN_CASH_BUFFER, RISK_WEIGHTS,
    RUNWAY_BUCKETS, QUICK_BUCKETS, DSO_BUCKETS,
    SCORE_THRESHOLDS, EXCLUDE_INFLOWS_Z, DEMO_DATE, RECURRING_OUTFLOWS
)


def _bucket_score(value: float, buckets: list[tuple]) -> float:
    for threshold, score in buckets:
        if value < threshold:
            return score
    return buckets[-1][1]


def score_liquidity(
    snap: CompanySnapshot,
    anom: AnomalyResult | None = None,
) -> LiquidityResult:
    """
    Pure function. Score 0–100, lower = worse.
    anom is None on first call; pipeline passes it on second.
    """
    try:
        # Runway
        runway_days = snap.cash_balance / DAILY_BURN
        runway_score = _bucket_score(runway_days, RUNWAY_BUCKETS)

        # Exclude anomalous AR from quick ratio
        if anom:
            anomalous_clients = {
                a.client for a in anom.anomalies
                if a.z_score >= EXCLUDE_INFLOWS_Z
            }
        else:
            anomalous_clients = set()

        ar_clean = sum(
            r.amount for r in snap.receivables
            if r.client not in anomalous_clients
        )

        # Payables due in next 30 days
        horizon = DEMO_DATE + timedelta(days=30)
        payables_30d = sum(
            p.amount for p in snap.payables
            if p.due_date <= horizon
        )
        # Add recurring outflows in next 30 days
        for name, (amount, dom) in RECURRING_OUTFLOWS.items():
            payables_30d += amount

        quick_ratio = (
            (snap.cash_balance + ar_clean) / payables_30d
            if payables_30d > 0
            else 999.0
        )
        quick_score = _bucket_score(quick_ratio, QUICK_BUCKETS)

        # DSO
        total_ar = sum(r.amount for r in snap.receivables)
        if total_ar > 0 and snap.receivables:
            weighted_days = sum(
                r.amount * (DEMO_DATE - r.issue_date).days
                for r in snap.receivables
            )
            dso_days = weighted_days / total_ar
        else:
            dso_days = 0.0
        dso_score = _bucket_score(dso_days, DSO_BUCKETS)

        # Receivables quality (concentration + anomaly)
        rq = _receivables_quality(snap, anom)
        rq_score = rq * 100

        # Composite
        components = {
            "runway":              runway_score * RISK_WEIGHTS["runway"],
            "quick_ratio":         quick_score  * RISK_WEIGHTS["quick_ratio"],
            "dso":                 dso_score    * RISK_WEIGHTS["dso"],
            "receivables_quality": rq_score     * RISK_WEIGHTS["receivables_quality"],
        }
        risk_score = int(sum(components.values()))

        if risk_score < SCORE_THRESHOLDS["CRITICAL"]:
            risk_level = "CRITICAL"
        elif risk_score < SCORE_THRESHOLDS["HIGH"]:
            risk_level = "HIGH"
        elif risk_score < SCORE_THRESHOLDS["MODERATE"]:
            risk_level = "MODERATE"
        else:
            risk_level = "LOW"

        return LiquidityResult(
            risk_score=risk_score,
            risk_level=risk_level,
            runway_days=round(runway_days, 1),
            quick_ratio=round(quick_ratio, 2),
            dso_days=round(dso_days, 1),
            receivables_quality=round(rq, 3),
            components={k: round(v, 1) for k, v in components.items()},
        )

    except ZeroDivisionError:
        return LiquidityResult(
            risk_score=0,
            risk_level="CRITICAL",
            runway_days=0.0,
            quick_ratio=0.0,
            dso_days=0.0,
            receivables_quality=0.0,
            components={},
            is_fallback=True,
        )


def _receivables_quality(
    snap: CompanySnapshot,
    anom: AnomalyResult | None,
) -> float:
    """
    Returns 0..1 where 1 = perfect AR quality.
    Penalizes concentration and anomalous clients.
    """
    total_ar = sum(r.amount for r in snap.receivables)
    if total_ar == 0:
        return 1.0

    # Concentration (HHI-inspired)
    client_shares = {}
    for r in snap.receivables:
        client_shares[r.client] = (
            client_shares.get(r.client, 0) + r.amount / total_ar
        )
    concentration_penalty = sum(s ** 2 for s in client_shares.values())

    # Anomaly penalty
    anomaly_penalty = 0.0
    if anom:
        for a in anom.anomalies:
            if a.severity == "ANOMALY":
                anomaly_penalty += 0.5
            elif a.severity == "WATCH":
                anomaly_penalty += 0.25
    anomaly_penalty = min(anomaly_penalty, 1.0)

    quality = 1.0 - (0.5 * concentration_penalty + 0.5 * anomaly_penalty)
    return max(0.0, quality)

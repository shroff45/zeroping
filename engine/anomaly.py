# engine/anomaly.py
# E2 — Anomaly detection engine
# Pure function. No I/O. No datetime.now(). No random.
#
# ALGORITHM: t-score with dynamic thresholds per client.
#   df = n - 1  (one per client, NOT global)
#   t_watch   = scipy.stats.t.ppf(0.85, df)   — dynamic per client
#   t_anomaly = scipy.stats.t.ppf(0.95, df)   — dynamic per client
#   t_score   = (days_since_issue - mean) / (std / sqrt(n))
#
# WHY t NOT z:
#   We have n=6 observations per client. At n=6, the t-distribution
#   has heavy tails (df=5). A z-score would under-flag anomalies
#   in thin-tailed normal assumption. t is correct for small n.
#
# CENSORING:
#   A receivable that is still unpaid has days_since_issue growing.
#   The t-score is computed from current days_since_issue, which is
#   right-censored: the client MIGHT pay tomorrow. We flag this.
#   censored=True means t_score understates the true delay.
#
# GATES:
#   G04: Apex Builders → severity == "ANOMALY"
#   G05: Apex t_score > t_anomaly threshold (dynamic)
#   G06: Metro Interiors → severity == "NORMAL"
#   G07: Metro t_score < t_watch threshold (dynamic)
#   G08: Apex censored == True (still unpaid)

from __future__ import annotations

import math

from scipy.stats import t as t_dist

from core.schemas import CompanySnapshot, Anomaly, AnomalyResult
from core.config import DEMO_DATE, ANOMALY_MIN_HISTORY


def detect_anomalies(snap: CompanySnapshot) -> AnomalyResult:
    """
    For each open receivable, compute t-score against that client's
    historical payment days. Classify as ANOMALY / WATCH / NORMAL.

    Returns AnomalyResult with all receivables classified.
    Fallback: return NORMAL for every receivable (never blocks pipeline).
    """
    try:
        anomalies: list[Anomaly] = []

        for recv in snap.receivables:
            client = recv.client

            # Collect this client's historical days_to_pay
            hist = [
                ph.days_to_pay
                for ph in snap.payment_history
                if ph.client == client
            ]

            # Days since invoice was issued (this IS the anomaly metric)
            days_since = (DEMO_DATE - recv.issue_date).days

            # Days overdue for UI urgency (separate from anomaly metric)
            due = recv.issue_date.days + recv.terms_days if hasattr(recv.issue_date, 'days') else None
            days_overdue = max(0, (DEMO_DATE - recv.issue_date).days - recv.terms_days)

            # Censored: invoice still unpaid → t understates delay
            censored = True  # all receivables in snap are open (paid_date=NULL)

            if len(hist) < ANOMALY_MIN_HISTORY:
                # Insufficient history — classify as WATCH conservatively
                anomalies.append(Anomaly(
                    client=client,
                    invoice_amount=recv.amount,
                    days_since_issue=days_since,
                    days_overdue=days_overdue,
                    t_score=0.0,
                    t_watch=0.0,
                    t_anomaly=0.0,
                    mean_days=float(recv.terms_days),
                    std_days=0.0,
                    severity="WATCH",
                    censored=censored,
                ))
                continue

            n   = len(hist)
            df  = n - 1

            mean_days = sum(hist) / n
            # Sample standard deviation
            variance  = sum((x - mean_days) ** 2 for x in hist) / (n - 1)
            std_days  = math.sqrt(variance)

            if std_days < 1e-9:
                # All payments identical → any deviation is anomalous
                t_score = float("inf") if days_since > mean_days else 0.0
            else:
                # t-statistic: (observed - mean) / (std / sqrt(n))
                t_score = (days_since - mean_days) / (std_days / math.sqrt(n))

            # Dynamic thresholds for this client's sample size
            t_watch_thresh   = t_dist.ppf(0.85, df)   # 85th percentile
            t_anomaly_thresh = t_dist.ppf(0.95, df)   # 95th percentile

            if t_score >= t_anomaly_thresh:
                severity = "ANOMALY"
            elif t_score >= t_watch_thresh:
                severity = "WATCH"
            else:
                severity = "NORMAL"

            anomalies.append(Anomaly(
                client=client,
                invoice_amount=recv.amount,
                days_since_issue=days_since,
                days_overdue=days_overdue,
                t_score=round(t_score, 3),
                t_watch=round(float(t_watch_thresh), 3),
                t_anomaly=round(float(t_anomaly_thresh), 3),
                mean_days=round(mean_days, 1),
                std_days=round(std_days, 1),
                severity=severity,
                censored=censored,
            ))

        # Sort: ANOMALY first, WATCH second, NORMAL last
        anomalies.sort(key=lambda a: {"ANOMALY": 0, "WATCH": 1, "NORMAL": 2}[a.severity])

        return AnomalyResult(anomalies=tuple(anomalies))

    except Exception:
        # Never block the pipeline — return safe fallback
        fallback = tuple(
            Anomaly(
                client=recv.client,
                invoice_amount=recv.amount,
                days_since_issue=0,
                days_overdue=0,
                t_score=0.0,
                t_watch=0.0,
                t_anomaly=0.0,
                mean_days=float(recv.terms_days),
                std_days=0.0,
                severity="NORMAL",
                censored=False,
            )
            for recv in snap.receivables
        )
        return AnomalyResult(anomalies=fallback, is_fallback=True)

import math
from collections import defaultdict
from core.schemas import CompanySnapshot, Anomaly, AnomalyResult
from core.config import (
    DEMO_DATE, ANOMALY_WATCH_Z, ANOMALY_FLAG_Z,
)


def detect_anomalies(snap: CompanySnapshot) -> AnomalyResult:
    history: dict[str, list[int]] = defaultdict(list)
    for r in snap.payment_history:
        history[r.client].append(r.days_to_pay)

    anomalies = []
    for recv in snap.receivables:

        days_since = (DEMO_DATE - recv.issue_date).days
        days_overdue = max(0, days_since - recv.terms_days)
        client_history = history.get(recv.client, [])
        n = len(client_history)

        if n < 4:
            if days_overdue > 60:
                severity = "ANOMALY"
            elif days_overdue > 14:
                severity = "WATCH"
            else:
                severity = "NORMAL"
            z = 0.0
            mean = 0.0
            std = 0.0
            is_fallback = True
        else:
            mean = sum(client_history) / n
            variance = sum((x - mean) ** 2 for x in client_history) / (n - 1)
            std = math.sqrt(variance)

            if std < 0.01:
                z = 0.0
                severity = "WATCH" if days_since > mean + 7 else "NORMAL"
            else:
                z = (days_since - mean) / std
                if z >= ANOMALY_FLAG_Z:
                    severity = "ANOMALY"
                elif z >= ANOMALY_WATCH_Z:
                    severity = "WATCH"
                else:
                    severity = "NORMAL"
            is_fallback = False

        anomalies.append(Anomaly(
            client=recv.client,
            invoice_amount=recv.amount,
            days_since_issue=days_since,
            days_overdue=days_overdue,
            z_score=round(z, 2),
            mean_days=round(mean, 1),
            std_days=round(std, 2),
            severity=severity,
            censored=True,
        ))

    return AnomalyResult(
        anomalies=tuple(sorted(anomalies, key=lambda a: -a.z_score)),
        is_fallback=any(
            len(history.get(a.client, [])) < 4
            for a in anomalies
        ),
    )

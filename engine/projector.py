# engine/projector.py

import math
from datetime import timedelta
from core.schemas import (
    CompanySnapshot, AnomalyResult, ProjectionResult,
)
from core.config import (
    DEMO_DATE, RECURRING_OUTFLOWS, EXCLUDE_INFLOWS_Z,
)


def project_cashflow(
    snap: CompanySnapshot,
    anom: AnomalyResult,
) -> ProjectionResult:
    """
    Daily ledger simulation, 90 days from DEMO_DATE.
    This is the DO-NOTHING baseline — optimizer not applied.

    Step 1: Expand recurring outflow templates
    Step 2: Place one-off payables on due dates
    Step 3: Expected inflows (excluding anomalous AR)
    Step 4: Cumulative expected balance
    Step 5: t-based prediction interval (widening with horizon)
    """
    try:
        horizon = 90
        days = list(range(horizon))

        # Daily cash flows
        flows = [0.0] * horizon

        # Step 1: Recurring outflows
        for month_offset in range(3):
            for name, (amount, dom) in RECURRING_OUTFLOWS.items():
                pay_date = _nth_day_of_month(DEMO_DATE, month_offset, dom)
                day_idx = (pay_date - DEMO_DATE).days
                if 0 <= day_idx < horizon:
                    flows[day_idx] -= amount

        # Step 2: One-off payables
        for p in snap.payables:
            day_idx = (p.due_date - DEMO_DATE).days
            if 0 <= day_idx < horizon:
                flows[day_idx] -= p.amount

        # Step 3: Expected inflows (exclude anomalous AR)
        anomalous_clients = {
            a.client for a in anom.anomalies
            if a.z_score >= EXCLUDE_INFLOWS_Z
        }
        excluded = []
        for r in snap.receivables:
            if r.client in anomalous_clients:
                excluded.append(r.client)
                continue
            hist = [
                ph.days_to_pay for ph in snap.payment_history
                if ph.client == r.client
            ]
            if hist:
                expected_days = int(
                    math.ceil(sum(hist) / len(hist))
                )
            else:
                expected_days = r.terms_days
            day_idx = (r.issue_date + timedelta(days=expected_days)
                       - DEMO_DATE).days
            if 0 <= day_idx < horizon:
                flows[day_idx] += r.amount

        # Step 4: Cumulative balance
        balance = snap.cash_balance
        daily_expected = []
        for f in flows:
            balance += f
            daily_expected.append(round(balance, 2))

        # Crossover and min balance
        crossover_day = next(
            (i for i, b in enumerate(daily_expected) if b < 0),
            None
        )
        min_bal = min(daily_expected)
        min_bal_day = daily_expected.index(min_bal)

        # Step 5: t-based prediction interval
        daily_lower, daily_upper = _prediction_band(
            snap, daily_expected
        )

        return ProjectionResult(
            daily_expected=tuple(daily_expected),
            daily_lower=tuple(daily_lower),
            daily_upper=tuple(daily_upper),
            crossover_day=crossover_day,
            min_balance=round(min_bal, 2),
            min_balance_day=min_bal_day,
            day30=round(daily_expected[29], 2),
            day60=round(daily_expected[59], 2),
            day90=round(daily_expected[89], 2),
            excluded_receivables=tuple(set(excluded)),
        )

    except Exception:
        # Minimal fallback
        flat = [snap.cash_balance] * horizon
        return ProjectionResult(
            daily_expected=tuple(flat),
            daily_lower=tuple(flat),
            daily_upper=tuple(flat),
            crossover_day=None,
            min_balance=snap.cash_balance,
            min_balance_day=0,
            day30=snap.cash_balance,
            day60=snap.cash_balance,
            day90=snap.cash_balance,
            excluded_receivables=(),
            is_fallback=True,
        )


def _prediction_band(
    snap: CompanySnapshot,
    daily_expected: list[float],
) -> tuple[list[float], list[float]]:
    """
    t-based PREDICTION interval (not confidence interval).
    df = n - 2 (2 fitted parameters: slope + intercept)
    n = 6 → df = 4 → t(0.95, 4) = 2.132

    se(h) = s * sqrt(1 + 1/n + (h - h_bar)^2 / Σ(h - h_bar)^2)
    Band WIDENS with horizon. This is correct and the demo line.
    """
    from scipy import stats

    nets = [m.net_flow for m in snap.monthly_history]
    n = len(nets)
    if n < 3:
        return daily_expected.copy(), daily_expected.copy()

    h_bar = sum(range(n)) / n
    ss_h = sum((i - h_bar) ** 2 for i in range(n))
    residuals = []
    # Simple linear fit
    x = list(range(n))
    slope = (
        sum((x[i] - h_bar) * (nets[i] - sum(nets)/n) for i in range(n))
        / ss_h if ss_h > 0 else 0
    )
    intercept = sum(nets)/n - slope * h_bar
    for i in range(n):
        residuals.append(nets[i] - (slope * x[i] + intercept))
    s = math.sqrt(sum(r**2 for r in residuals) / max(n - 2, 1))

    df = max(n - 2, 1)
    t_crit = stats.t.ppf(0.95, df)   # one-tail 95%

    monthly_scale = abs(sum(nets) / n) if nets else 1.0

    lower, upper = [], []
    for day_idx, bal in enumerate(daily_expected):
        month_horizon = day_idx / 30.0
        h = n + month_horizon
        se = s * math.sqrt(
            1 + 1/n + (h - h_bar)**2 / (ss_h if ss_h > 0 else 1)
        )
        band = t_crit * se
        lower.append(round(bal - band, 2))
        upper.append(round(bal + band, 2))

    return lower, upper


def _nth_day_of_month(
    from_date, month_offset: int, dom: int
) -> "date":
    """Return date(year, month, dom) clamped to month-end."""
    import calendar
    from datetime import date
    m = from_date.month + month_offset
    y = from_date.year + (m - 1) // 12
    m = ((m - 1) % 12) + 1
    last = calendar.monthrange(y, m)[1]
    return date(y, m, min(dom, last))

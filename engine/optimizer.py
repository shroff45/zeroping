# engine/optimizer.py
# E4 — Payment optimizer
# Pure function. No I/O. No datetime.now(). No random.
# Owner: Pranav
# Deps: B05, B06
#
# ALGORITHM: Mixed Integer Linear Program (MILP) via HiGHS solver.
#
#   OBJECTIVE:
#     Maximize total payment throughput subject to cash floor constraint.
#     In standard min-cost form (scipy.optimize.milp minimizes):
#       minimize: -Σ priority_i × amount_i × x_i
#     where x_i ∈ {0, 1}
#
#   VARIABLES:
#     x_i = 1 → pay bill i now
#     x_i = 0 → schedule or defer
#
#   CONSTRAINTS:
#     C1: Σ(amount_i × x_i) ≤ cash - MIN_CASH_BUFFER  (cash floor)
#     C2: x_i = 1  for hard non-flexible bills due ≤ HARD_DAYS  (forced payment)
#
#   PRIORITY WEIGHTS (for objective):
#     Non-flexible, overdue:           4.0  (pay immediately)
#     Non-flexible, due in ≤ 3 days:  3.0
#     Non-flexible, due in ≤ 7 days:  2.5
#     Non-flexible, due later:        2.0
#     Flexible, due soon:             1.0
#     Flexible, due later:            0.5
#
#   POST-SOLVE CLASSIFICATION:
#     x_i = 1  AND non-flexible        → PAY_NOW
#     x_i = 0  AND non-flexible        → SCHEDULED (blocked on collections)
#     x_i = 1  AND flexible            → PAY_NOW
#     x_i = 0  AND flexible            → DEFER
#
#   HARD DEADLINE FORCING (C2):
#     Non-flexible bills due in ≤ HARD_DAYS (7) are forced into PAY_NOW
#     regardless of whether the solver would exclude them.
#     If cash insufficient after forcing, they remain SCHEDULED.
#
#   FALLBACK:
#     If MILP fails (infeasible, solver error): greedy priority sort.
#     The fallback must produce the same classifications as the MILP
#     on the demo seed data — test this in check.py.
#
# GATES:
#   G14: Prestige Properties (rent) → PAY_NOW
#   G15: cash_after rent correct
#   G16: Staff Salaries → SCHEDULED
#   G17: Sharma Timber → DEFER
#   G18: spendable_now = cash - buffer
#   G19: MILP solver used (HiGHS)
#   G20: MILP objective/constraints in docstring

from __future__ import annotations

import math
from datetime import date
from decimal import Decimal

from core.schemas import (
    CompanySnapshot,
    LiquidityResult,
    AnomalyResult,
    ProjectionResult,
    PaymentDecision,
    PaymentPlan,
)
from core.config import DEMO_DATE, MIN_CASH_BUFFER, OPTIMIZER_HARD_DAYS
from core.money import to_decimal, format_inr

# Anomaly import for blocker identification
from core.schemas import Anomaly


def optimize_payments(
    snap: CompanySnapshot,
    liq: LiquidityResult,
    anom: AnomalyResult,
    proj: ProjectionResult,
) -> PaymentPlan:
    """
    MILP-based payment scheduler.

    Maximize total payment throughput subject to:
      (C1) cash remains above MIN_CASH_BUFFER after all payments
      (C2) non-flexible bills due in ≤ HARD_DAYS are forced into solution

    See module docstring for full MILP formulation.
    Falls back to greedy sort if HiGHS is unavailable or infeasible.
    """
    in_crisis = liq.risk_level in ("HIGH", "CRITICAL")

    # Identify anomalous clients for SCHEDULED reason strings
    anomalous: dict[str, Anomaly] = {
        a.client: a
        for a in anom.anomalies
        if a.severity == "ANOMALY"
    }

    # Spendable budget (cash above the non-negotiable buffer)
    cash         = to_decimal(snap.cash_balance)
    buffer       = to_decimal(MIN_CASH_BUFFER)
    spendable    = cash - buffer

    payables     = list(snap.payables)
    n            = len(payables)

    if n == 0:
        return PaymentPlan(decisions=(), spendable_now=float(spendable))

    # ── MILP solve ────────────────────────────────────────────────────
    decisions = _solve_milp(
        payables    = payables,
        cash        = float(cash),
        spendable   = float(spendable),
        in_crisis   = in_crisis,
        anomalous   = anomalous,
    )

    if decisions is None:
        # Fallback: greedy priority sort
        decisions = _greedy_fallback(
            payables  = payables,
            cash      = float(cash),
            spendable = float(spendable),
            in_crisis = in_crisis,
            anomalous = anomalous,
        )

    return PaymentPlan(
        decisions=tuple(decisions),
        spendable_now=round(float(spendable), 2),
    )


def _priority(payable, in_crisis: bool) -> float:
    """
    Priority weight for MILP objective and greedy fallback.
    Higher = more urgent to pay.
    """
    days_until = (payable.due_date - DEMO_DATE).days

    if not payable.flexible:
        if days_until <= 0:
            return 4.0    # overdue
        if days_until <= 3:
            return 3.0    # imminent
        if days_until <= 7:
            return 2.5    # due this week
        return 2.0         # due later but hard deadline
    else:
        # Flexible: low priority, especially in crisis
        if in_crisis:
            return 0.2    # deprioritize strongly
        if days_until <= 7:
            return 1.0
        return 0.5


def _solve_milp(
    payables: list,
    cash: float,
    spendable: float,
    in_crisis: bool,
    anomalous: dict,
) -> list[PaymentDecision] | None:
    """
    Solve payment optimization via MILP (HiGHS).

    Objective (minimization form):
      min -Σ priority_i × amount_i × x_i
    Subject to:
      Σ amount_i × x_i ≤ spendable      (C1: cash floor)
      x_i = 1  for i in forced_set       (C2: hard deadlines ≤ HARD_DAYS)
      x_i ∈ {0, 1}                       (binary integrality)

    Returns list of PaymentDecision or None if solve fails.
    """
    try:
        import numpy as np
        from scipy.optimize import milp, LinearConstraint, Bounds

        n = len(payables)
        priorities = [_priority(p, in_crisis) for p in payables]
        amounts    = [float(p.amount) for p in payables]

        # Objective: minimize -Σ priority_i × amount_i × x_i
        c = np.array([-priorities[i] * amounts[i] for i in range(n)], dtype=float)

        # C1: Σ amount_i × x_i ≤ spendable
        A_ub = np.array([amounts], dtype=float)
        constraint = LinearConstraint(A_ub, lb=-np.inf, ub=spendable)

        # Bounds: x_i ∈ [0, 1]
        bounds = Bounds(lb=0, ub=1)

        # Integrality: 1 = integer, 0 = continuous (all binary here)
        integrality = np.ones(n, dtype=int)

        # C2: Force hard deadline non-flexible bills due in ≤ HARD_DAYS
        # Enforce via bounds: fix x_i lower bound to 1 if forced
        lb_arr = np.zeros(n, dtype=float)
        for i, p in enumerate(payables):
            days_until = (p.due_date - DEMO_DATE).days
            if not p.flexible and days_until <= OPTIMIZER_HARD_DAYS:
                lb_arr[i] = 1.0   # force into solution

        bounds = Bounds(lb=lb_arr, ub=1.0)

        result = milp(
            c=c,
            constraints=constraint,
            integrality=integrality,
            bounds=bounds,
        )

        if not result.success:
            return None

        # ── Post-solve classification ──────────────────────────────
        x = result.x
        decisions: list[PaymentDecision] = []
        running_cash = cash

        # Sort by priority descending to build cash_after sequence
        order = sorted(range(n), key=lambda i: (_priority(payables[i], in_crisis)), reverse=True)

        selected  = {i for i in range(n) if x[i] > 0.5}
        scheduled = {i for i in range(n) if i not in selected and not payables[i].flexible}
        deferred  = {i for i in range(n) if i not in selected and payables[i].flexible}

        # PAY_NOW first (in priority order, to track cash_after)
        for i in order:
            p = payables[i]
            days_until = (p.due_date - DEMO_DATE).days
            if i in selected:
                running_cash -= p.amount
                decisions.append(PaymentDecision(
                    payee     = p.payee,
                    amount    = p.amount,
                    due_date  = p.due_date,
                    action    = "PAY_NOW",
                    reason    = _pay_now_reason(days_until),
                    cash_after= round(running_cash, 2),
                ))

        # SCHEDULED
        for i in order:
            p = payables[i]
            if i in scheduled:
                decisions.append(PaymentDecision(
                    payee     = p.payee,
                    amount    = p.amount,
                    due_date  = p.due_date,
                    action    = "SCHEDULED",
                    reason    = _scheduled_reason(anomalous, p, running_cash),
                    cash_after= None,
                ))

        # DEFER
        for i in order:
            p = payables[i]
            if i in deferred:
                decisions.append(PaymentDecision(
                    payee     = p.payee,
                    amount    = p.amount,
                    due_date  = p.due_date,
                    action    = "DEFER",
                    reason    = "flexible — negotiate extra time, preserve runway",
                    cash_after= None,
                ))

        return decisions

    except Exception:
        return None


def _greedy_fallback(
    payables: list,
    cash: float,
    spendable: float,
    in_crisis: bool,
    anomalous: dict,
) -> list[PaymentDecision]:
    """
    Greedy fallback when MILP fails.
    Non-flexible first (sorted by due date), then flexible.
    Produces same result as MILP on demo seed data.
    """
    sorted_payables = sorted(
        enumerate(payables),
        key=lambda ip: (int(ip[1].flexible), ip[1].due_date),
    )

    decisions: list[PaymentDecision] = []
    running_cash = cash

    for _, p in sorted_payables:
        days_until = (p.due_date - DEMO_DATE).days

        if not p.flexible:
            can_afford = p.amount <= (running_cash - float(to_decimal(str(MIN_CASH_BUFFER))))
            if can_afford:
                running_cash -= p.amount
                decisions.append(PaymentDecision(
                    payee     = p.payee,
                    amount    = p.amount,
                    due_date  = p.due_date,
                    action    = "PAY_NOW",
                    reason    = _pay_now_reason(days_until),
                    cash_after= round(running_cash, 2),
                ))
            else:
                decisions.append(PaymentDecision(
                    payee     = p.payee,
                    amount    = p.amount,
                    due_date  = p.due_date,
                    action    = "SCHEDULED",
                    reason    = _scheduled_reason(anomalous, p, running_cash),
                    cash_after= None,
                ))
        else:
            if in_crisis and days_until > 7:
                decisions.append(PaymentDecision(
                    payee     = p.payee,
                    amount    = p.amount,
                    due_date  = p.due_date,
                    action    = "DEFER",
                    reason    = "flexible — negotiate extra time, preserve runway",
                    cash_after= None,
                ))
            elif p.amount <= (running_cash - MIN_CASH_BUFFER):
                running_cash -= p.amount
                decisions.append(PaymentDecision(
                    payee     = p.payee,
                    amount    = p.amount,
                    due_date  = p.due_date,
                    action    = "PAY_NOW",
                    reason    = f"affordable — due {p.due_date.strftime('%b %d')}",
                    cash_after= round(running_cash, 2),
                ))
            else:
                decisions.append(PaymentDecision(
                    payee     = p.payee,
                    amount    = p.amount,
                    due_date  = p.due_date,
                    action    = "DEFER",
                    reason    = "exceeds spendable cash — defer",
                    cash_after= None,
                ))

    return decisions


# ── Reason string builders ────────────────────────────────────────────
# Engine-written. ≤ 90 chars. No LLM involved.

def _pay_now_reason(days_until: int) -> str:
    if days_until <= 0:
        return "overdue — pay immediately"
    if days_until <= 2:
        return f"due in {days_until}d — pay today"
    if days_until <= 7:
        return f"due in {days_until}d — pay now"
    return f"due in {days_until}d — affordable, schedule payment"


def _scheduled_reason(
    anomalous: dict,
    payable,
    running_cash: float,
) -> str:
    """
    Explain why this bill cannot be paid right now.
    Names the primary blocking client if one exists.
    Hard limit: 90 chars.
    """
    if anomalous:
        blocker_client = next(iter(anomalous))
        blocker = anomalous[blocker_client]
        reason = (
            f"blocked — collect {blocker_client} "
            f"{format_inr(blocker.invoice_amount)} first"
        )
    else:
        shortfall = payable.amount - (running_cash - MIN_CASH_BUFFER)
        reason = f"shortfall {format_inr(shortfall)} — awaiting collections"

    return reason[:90]

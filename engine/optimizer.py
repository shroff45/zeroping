# engine/optimizer.py
# B12 — Payment optimizer
# Pure function. No I/O. No datetime.now(). No random.
# Owner: Pranav
# Deps: B05, B06
#
# Consumes liq + anom + proj.
# proj is the DO-NOTHING baseline and is NEVER recomputed
# with the plan applied — no circular dependency.
#
# Three-state actions:
#   PAY_NOW   — affordable, hard deadline or imminent
#   SCHEDULED — must pay, cash insufficient, blocked on collection
#   DEFER     — flexible payable, negotiate extra time

from __future__ import annotations

from datetime import date
from core.schemas import (
    CompanySnapshot,
    LiquidityResult,
    AnomalyResult,
    ProjectionResult,
    PaymentDecision,
    PaymentPlan,
    Anomaly,
)
from core.config import DEMO_DATE, MIN_CASH_BUFFER
from core.money import format_inr


def optimize_payments(
    snap: CompanySnapshot,
    liq: LiquidityResult,
    anom: AnomalyResult,
    proj: ProjectionResult,
) -> PaymentPlan:
    """
    Greedy priority-ordered payment scheduler.

    Sort order: non-flexible first, then by due date ascending.
    Within non-flexible: earlier due date = higher priority.

    CRITICAL/HIGH mode: never pay a flexible bill > 7 days early.
    Buffer: MIN_CASH_BUFFER is always preserved.
    """
    in_crisis = liq.risk_level in ("HIGH", "CRITICAL")

    # Identify clients blocking cash collection
    anomalous: dict[str, "Anomaly"] = {
        a.client: a
        for a in anom.anomalies
        if a.severity == "ANOMALY"
    }

    # Running cash state — starts at full balance
    running_cash = snap.cash_balance
    spendable = snap.cash_balance - MIN_CASH_BUFFER

    # Sort: non-flexible bills first, then by due date
    sorted_payables = sorted(
        snap.payables,
        key=lambda p: (int(p.flexible), p.due_date),
    )

    decisions: list[PaymentDecision] = []

    for p in sorted_payables:
        days_until = (p.due_date - DEMO_DATE).days

        if not p.flexible:
            # Hard deadline — must pay
            can_afford = p.amount <= (running_cash - MIN_CASH_BUFFER)

            if can_afford:
                running_cash -= p.amount
                decisions.append(PaymentDecision(
                    payee=p.payee,
                    amount=p.amount,
                    due_date=p.due_date,
                    action="PAY_NOW",
                    reason=_pay_now_reason(days_until),
                    cash_after=round(running_cash, 2),
                ))
            else:
                # Cannot afford — find the blocker
                reason = _scheduled_reason(anomalous, p, running_cash)
                decisions.append(PaymentDecision(
                    payee=p.payee,
                    amount=p.amount,
                    due_date=p.due_date,
                    action="SCHEDULED",
                    reason=reason,
                    cash_after=None,
                ))

        else:
            # Flexible payable — can we and should we pay?
            if in_crisis and days_until > 7:
                # Preserve runway — defer flexible bills in crisis
                decisions.append(PaymentDecision(
                    payee=p.payee,
                    amount=p.amount,
                    due_date=p.due_date,
                    action="DEFER",
                    reason="flexible — negotiate extra time, preserve runway",
                    cash_after=None,
                ))
            elif p.amount <= (running_cash - MIN_CASH_BUFFER):
                running_cash -= p.amount
                decisions.append(PaymentDecision(
                    payee=p.payee,
                    amount=p.amount,
                    due_date=p.due_date,
                    action="PAY_NOW",
                    reason=f"affordable — due {p.due_date.strftime('%b %d')}",
                    cash_after=round(running_cash, 2),
                ))
            else:
                decisions.append(PaymentDecision(
                    payee=p.payee,
                    amount=p.amount,
                    due_date=p.due_date,
                    action="DEFER",
                    reason="exceeds spendable cash — defer",
                    cash_after=None,
                ))

    return PaymentPlan(
        decisions=tuple(decisions),
        spendable_now=round(snap.cash_balance - MIN_CASH_BUFFER, 2),
    )


# ── Reason string builders ────────────────────────────────────────────
# Engine-written, ≤ 90 chars, no LLM involved.

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
    Names the blocking client if one exists.
    Hard limit: 90 chars.
    """
    if anomalous:
        # Name the primary blocker
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

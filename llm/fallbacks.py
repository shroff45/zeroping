# llm/fallbacks.py
# B13.5 — Pre-verified fallback narratives
# Owner: Sai
# Deps: B05, core/money.py
#
# RULE: Write fallbacks BEFORE prompts.
# These define what "good output" looks like.
# They also guarantee the UI works with zero Ollama dependency.
#
# Fallbacks are engine-computed strings assembled into
# the same dict shape that the LLM is expected to return.
# No invented numbers. No hedging. No placeholders.
# Every number comes from the AnalysisResult passed in.

from __future__ import annotations

from core.schemas import AnalysisResult
from core.money import format_inr


def dashboard_fallback(result: AnalysisResult) -> dict:
    """
    Fallback dashboard narrative.
    Same dict shape as SCHEMA_DASHBOARD in prompts.py.
    Keys: headline, finding_1, finding_2, finding_3, action.
    All numbers sourced from result. Zero invented.
    """
    liq  = result.liquidity
    proj = result.projection

    # Find the worst anomaly (sorted by z_score desc in engine)
    apex = next(
        (a for a in result.anomalies.anomalies
         if a.severity == "ANOMALY"),
        None,
    )

    # Find the SCHEDULED payment (the blocked bill)
    scheduled = next(
        (d for d in result.payments.decisions
         if d.action == "SCHEDULED"),
        None,
    )

    # Headline — risk level + most urgent fact
    if apex:
        headline = (
            f"Cash runway is {liq.runway_days:.0f} days and risk is "
            f"{liq.risk_level} — {apex.client} has not paid "
            f"{format_inr(apex.invoice_amount)} in "
            f"{apex.days_since_issue} days."
        )
    else:
        headline = (
            f"Cash runway is {liq.runway_days:.0f} days. "
            f"Risk level is {liq.risk_level}. "
            f"Review overdue invoices immediately."
        )

    # Finding 1 — anomaly detail
    if apex:
        finding_1 = (
            f"{apex.client} has not paid {format_inr(apex.invoice_amount)} in "
            f"{apex.days_overdue} days — "
            f"t-score {apex.t_score:.2f} exceeds their {apex.t_anomaly:.2f} threshold."
        )
    else:
        finding_1 = (
            f"No single anomalous client detected. "
            f"DSO is {liq.dso_days:.0f} days — "
            f"review all open invoices for collection priority."
        )

    # Finding 2 — projection / crossover
    if proj.crossover_day is not None:
        finding_2 = (
            f"If no collections arrive, cash goes negative on "
            f"Day {proj.crossover_day}. "
            f"Minimum balance over 90 days is "
            f"{format_inr(proj.min_balance)} on Day {proj.min_balance_day}."
        )
    else:
        finding_2 = (
            f"No cash crossover within 90 days under the baseline. "
            f"Day 30 balance: {format_inr(proj.day30)}. "
            f"Day 90 balance: {format_inr(proj.day90)}."
        )

    # Finding 3 — payments situation
    if scheduled:
        finding_3 = (
            f"{scheduled.payee} of {format_inr(scheduled.amount)} "
            f"cannot be paid right now. "
            f"Reason: {scheduled.reason}."
        )
    else:
        finding_3 = (
            f"Spendable cash is {format_inr(result.payments.spendable_now)} "
            f"after the minimum buffer. "
            f"All current bills can be met."
        )

    # Action — one concrete step
    if apex:
        action = (
            f"Call {apex.client} today. Their {format_inr(apex.invoice_amount)} "
            f"payment is {apex.days_overdue} days overdue and is blocking "
            f"your salary run. Request partial payment immediately."
        )
    else:
        action = (
            f"Review all open invoices and prioritise collection. "
            f"Spendable cash is {format_inr(result.payments.spendable_now)}."
        )

    return {
        "headline":  headline,
        "finding_1": finding_1,
        "finding_2": finding_2,
        "finding_3": finding_3,
        "action":    action,
    }


def email_fallback(result: AnalysisResult, client_name: str) -> dict:
    """
    Fallback collection email + WhatsApp message.
    Same dict shape as SCHEMA_EMAIL in prompts.py.
    Keys: subject, body, whatsapp.
    """
    apex = next(
        (a for a in result.anomalies.anomalies
         if a.client == client_name),
        None,
    )
    if not apex:
        return {"subject": "", "body": "", "whatsapp": ""}

    amt = format_inr(apex.invoice_amount)
    return {
        "subject": (
            f"Payment Follow-up — Invoice Outstanding {amt}"
        ),

        "body": (
            f"Dear {client_name} Team,\n\n"
            f"I hope this message finds you well. "
            f"I'm writing regarding our invoice of {amt}, "
            f"issued {apex.days_since_issue} days ago "
            f"and now {apex.days_overdue} days overdue.\n\n"
            f"Historically, you've settled our invoices in "
            f"approximately {apex.mean_days:.0f} days, "
            f"which we genuinely appreciate. "
            f"This invoice is significantly overdue, "
            f"and we'd be grateful if you could arrange "
            f"payment at the earliest, or share a timeline.\n\n"
            f"Please don't hesitate to reach out if there's "
            f"anything we can clarify.\n\n"
            f"Warm regards,\nPriya Designs"
        ),

        "whatsapp": (
            f"Hi, this is Priya Designs. Our invoice of {amt} "
            f"is {apex.days_overdue} days overdue. "
            f"Could you share a payment date? Thank you."
        ),
    }
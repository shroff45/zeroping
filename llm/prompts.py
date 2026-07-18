# llm/prompts.py
# B13.3 — Prompt construction + JSON schema contracts
# Owner: Sai
# Deps: core/schemas.py, core/money.py
#
# RULE:
#   LLM narrates numbers the engines computed.
#   It never computes.
#   It never estimates.
#   It never invents.
#
# Every numeric value passed here must already be formatted.
# The model is instructed to COPY amounts verbatim.

from __future__ import annotations

from core.schemas import AnalysisResult
from core.money import format_inr


# ─────────────────────────────────────────────────────────────
# JSON SCHEMAS
# ─────────────────────────────────────────────────────────────

SCHEMA_DASHBOARD = {
    "type": "object",
    "properties": {
        "headline":  {"type": "string"},
        "finding_1": {"type": "string"},
        "finding_2": {"type": "string"},
        "finding_3": {"type": "string"},
        "action":    {"type": "string"},
    },
    "required": ["headline", "finding_1", "finding_2", "finding_3", "action"],
}

SCHEMA_EMAIL = {
    "type": "object",
    "properties": {
        "subject":  {"type": "string"},
        "body":     {"type": "string"},
        "whatsapp": {"type": "string"},
    },
    "required": ["subject", "body", "whatsapp"],
}


# ─────────────────────────────────────────────────────────────
# DASHBOARD PROMPT
# ─────────────────────────────────────────────────────────────

def dashboard_messages(result: AnalysisResult) -> list[dict]:
    """
    Build messages for dashboard narrative.
    All numbers are pre-formatted.
    """

    liq  = result.liquidity
    proj = result.projection

    apex = next(
        (a for a in result.anomalies.anomalies if a.severity == "ANOMALY"),
        None,
    )

    scheduled = next(
        (d for d in result.payments.decisions if d.action == "SCHEDULED"),
        None,
    )

    # Pre-format all numbers before sending to model
    runway_days     = f"{liq.runway_days:.0f}"
    risk_level      = liq.risk_level
    risk_score      = str(liq.risk_score)
    min_balance     = format_inr(proj.min_balance)
    min_balance_day = str(proj.min_balance_day)

    crossover = (
        f"Day {proj.crossover_day}"
        if proj.crossover_day is not None
        else "Not within 90 days"
    )

    if apex:
        apex_block = (
            f"{apex.client}: "
            f"{format_inr(apex.invoice_amount)}, "
            f"{apex.days_overdue} days overdue, "
            f"{apex.z_score:.1f}σ beyond normal"
        )
    else:
        apex_block = "No anomalous client detected."

    if scheduled:
        scheduled_block = (
            f"{scheduled.payee}: {format_inr(scheduled.amount)} "
            f"cannot be paid. Reason: {scheduled.reason}"
        )
    else:
        scheduled_block = "All current bills can be met."

    system = (
        "You are a financial advisor for an Indian SME owner.\n"
        "Write in plain English. No jargon.\n"
        "Copy all ₹ amounts and numbers exactly as provided.\n"
        "Do NOT compute anything.\n"
        "Return JSON only.\n"
    )

    user = (
        f"Risk level: {risk_level} ({risk_score}/100)\n"
        f"Runway: {runway_days} days\n"
        f"Crossover: {crossover}\n"
        f"Minimum balance: {min_balance} on day {min_balance_day}\n\n"
        f"Anomaly detail: {apex_block}\n"
        f"Payment constraint: {scheduled_block}\n\n"
        "Write:\n"
        "- headline\n"
        "- finding_1\n"
        "- finding_2\n"
        "- finding_3\n"
        "- action\n"
        "Each 2–3 sentences maximum."
    )

    return [
        {"role": "system", "content": system},
        {"role": "user",   "content": user},
    ]


# ─────────────────────────────────────────────────────────────
# EMAIL PROMPT
# ─────────────────────────────────────────────────────────────

def email_messages(result: AnalysisResult, client_name: str) -> list[dict]:
    """
    Build messages for collection email generation.
    """

    apex = next(
        (a for a in result.anomalies.anomalies
         if a.client == client_name),
        None,
    )

    if not apex:
        return []

    amount_str     = format_inr(apex.invoice_amount)
    amount_prompt  = format_inr(apex.invoice_amount, symbol="Rs. ")
    days_since     = str(apex.days_since_issue)
    days_overdue   = str(apex.days_overdue)
    mean_days      = f"{apex.mean_days:.0f}"

    system = (
        "You are drafting a professional collection email "
        "for an Indian design studio owner.\n"
        "Firm but respectful tone.\n"
        "Copy all amounts exactly as given.\n"
        "Return JSON only.\n"
    )

    user = (
        f"Client: {client_name}\n"
        f"Invoice amount: {amount_str}\n"
        f"Days since issue: {days_since}\n"
        f"Days overdue: {days_overdue}\n"
        f"Historical average payment: {mean_days} days\n\n"
        "Generate:\n"
        "- subject\n"
        "- body\n"
        "- whatsapp\n"
        "WhatsApp must be under 60 words."
    )

    return [
        {"role": "system", "content": system},
        {"role": "user",   "content": user},
    ]

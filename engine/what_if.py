# engine/what_if.py
# What-if scenario engine
# Pure function. No I/O. No LLM.
#
# Simulates: "What happens if client X pays today?"
#   1. Remove that client's receivable from the snapshot
#   2. Re-run liquidity + projection on modified snapshot
#   3. Return delta and new risk level
#
# Used by MCP tool: run_what_if
# Snapshot accessed from result.snapshot (Q3 decision — no 4th session state key)

from __future__ import annotations

from core.schemas import (
    CompanySnapshot,
    WhatIfResult,
)
from core.money import to_decimal


def what_if_scenario(
    snap: CompanySnapshot,
    client_name: str,
) -> WhatIfResult:
    """
    Simulate a client paying their invoice today.

    Creates a modified snapshot:
      - Removes the client's receivable
      - Adds that receivable's amount to cash_balance

    Re-runs liquidity and projection on modified snapshot.

    Returns WhatIfResult with:
      - scenario_label: human-readable description
      - delta_cash: amount added to cash
      - new_crossover_day: updated projection
      - new_risk_level: updated risk level
      - payments_unlocked: bills that become PAY_NOW after collection
    """
    # Find the receivable for this client
    matching = [r for r in snap.receivables if r.client == client_name]
    if not matching:
        return WhatIfResult(
            scenario_label=f"{client_name} not found in open receivables",
            delta_cash=0.0,
            new_crossover_day=None,
            new_risk_level="CRITICAL",
            payments_unlocked=(),
        )

    recv  = matching[0]
    delta = recv.amount

    # Modified snapshot: remove receivable, add cash
    new_cash        = snap.cash_balance + delta
    new_receivables = tuple(r for r in snap.receivables if r.client != client_name)

    # Reconstruct frozen snapshot using model_dump() to prevent Streamlit hot-reload ValidationError
    new_snap = CompanySnapshot(
        as_of=snap.as_of,
        cash_balance=float(new_cash),
        receivables=tuple(r.model_dump() for r in new_receivables),
        payables=tuple(p.model_dump() for p in snap.payables),
        payment_history=tuple(h.model_dump() for h in snap.payment_history),
        monthly_history=tuple(m.model_dump() for m in snap.monthly_history),
    )

    # Re-run affected engines on modified snapshot
    from engine.anomaly import detect_anomalies
    from engine.liquidity import score_liquidity
    from engine.projector import project_cashflow
    from engine.optimizer import optimize_payments

    new_anom = detect_anomalies(new_snap)
    new_liq  = score_liquidity(new_snap, new_anom)
    new_proj = project_cashflow(new_snap, new_anom)
    new_opt  = optimize_payments(new_snap, new_liq, new_anom, new_proj)

    # Bills that would be unlocked (PAY_NOW) after collection
    payments_unlocked = tuple(
        d.payee
        for d in new_opt.decisions
        if d.action == "PAY_NOW"
    )

    return WhatIfResult(
        scenario_label=f"If {client_name} pays {format_inr_simple(recv.amount)} today",
        delta_cash=float(delta),
        new_crossover_day=new_proj.crossover_day,
        new_risk_level=new_liq.risk_level,
        payments_unlocked=payments_unlocked,
    )


def format_inr_simple(amount: float) -> str:
    """Minimal inline formatter to avoid circular import from core.money."""
    return f"₹{amount:,.0f}"

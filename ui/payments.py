# ui/payments.py
# B15.5 — Payments tab renderer
# Owner: Rishil
# Deps: B05, ui/styles.py, core/money.py
#
# RULES:
#   - Render only. No computation. No DB. No LLM.
#   - Three sections: PAY_NOW / SCHEDULED / DEFER in that order.
#   - Each section shows count + total amount.
#   - SCHEDULED rows always show the blocker reason.
#   - cash_after shown only for PAY_NOW rows.
#   - Spendable now shown at top with buffer explanation.

from __future__ import annotations

import streamlit as st

from core.schemas import AnalysisResult, PaymentDecision
from core.money import format_inr
from core.config import MIN_CASH_BUFFER


def render(result: AnalysisResult) -> None:
    """Render the payments tab."""

    plan = result.payments

    # ── Spendable header ──────────────────────────────────────
    st.metric(
        label="Spendable now",
        value=format_inr(plan.spendable_now),
        help=(
            f"Cash balance minus ₹{MIN_CASH_BUFFER:,} minimum buffer. "
            f"Never spend below the buffer."
        ),
    )

    # ── Summary row ───────────────────────────────────────────
    pay_now   = [d for d in plan.decisions if d.action == "PAY_NOW"]
    scheduled = [d for d in plan.decisions if d.action == "SCHEDULED"]
    deferred  = [d for d in plan.decisions if d.action == "DEFER"]

    c1, c2, c3 = st.columns(3)
    with c1:
        total = sum(d.amount for d in pay_now)
        st.metric(
            "Pay now",
            format_inr(total),
            f"{len(pay_now)} bill{'s' if len(pay_now) != 1 else ''}",
            delta_color="off",
        )
    with c2:
        total = sum(d.amount for d in scheduled)
        st.metric(
            "Scheduled (blocked)",
            format_inr(total),
            f"{len(scheduled)} bill{'s' if len(scheduled) != 1 else ''}",
            delta_color="off",
        )
    with c3:
        total = sum(d.amount for d in deferred)
        st.metric(
            "Deferred",
            format_inr(total),
            f"{len(deferred)} bill{'s' if len(deferred) != 1 else ''}",
            delta_color="off",
        )

    st.divider()

    # ── PAY NOW section ───────────────────────────────────────
    if pay_now:
        st.markdown("#### ✅ Pay Now")
        st.caption("Affordable and due soon. Pay these today.")
        for d in pay_now:
            _render_payment_row(d)

    # ── SCHEDULED section ─────────────────────────────────────
    if scheduled:
        st.markdown("#### 📅 Scheduled — Blocked")
        st.caption(
            "Must be paid but cash is insufficient. "
            "Blocked on collection. Resolve the blocker first."
        )
        for d in scheduled:
            _render_payment_row(d)

    # ── DEFER section ─────────────────────────────────────────
    if deferred:
        st.markdown("#### ⏸️ Defer")
        st.caption("Flexible bills. Negotiate extra time to preserve runway.")
        for d in deferred:
            _render_payment_row(d)

    # ── Plan explanation ──────────────────────────────────────
    st.divider()
    with st.expander("How this plan was built", expanded=False):
        st.markdown(
            "**Priority order:**\n"
            "1. Non-flexible bills sorted by due date\n"
            "2. Flexible bills deferred during CRITICAL/HIGH risk\n\n"
            "**PAY_NOW rule:** Non-flexible, affordable within buffer.\n\n"
            "**SCHEDULED rule:** Non-flexible, but cash insufficient "
            "after buffer. Blocked until collections arrive.\n\n"
            "**DEFER rule:** Flexible payable. "
            "Negotiate with vendor — preserve runway first.\n\n"
            f"**Buffer:** ₹{MIN_CASH_BUFFER:,} is always preserved. "
            "This is a fixed safety margin, not a percentage of burn."
        )

    # ── Cash waterfall ────────────────────────────────────────
    with st.expander("Cash waterfall (PAY_NOW sequence)", expanded=False):
        _render_waterfall(result)


# ── Private helpers ───────────────────────────────────────────────

def _render_payment_row(d: PaymentDecision) -> None:
    """Render one payment row with action-coloured styling."""

    st.markdown(
        f'<div class="payment-row pay-{d.action}">',
        unsafe_allow_html=True,
    )

    col1, col2 = st.columns([4, 2])

    with col1:
        st.markdown(f"**{d.payee}**")
        st.caption(d.reason)
        st.caption(f"Due: {d.due_date.strftime('%b %d, %Y')}")

    with col2:
        st.markdown(f"**{format_inr(d.amount)}**")
        if d.cash_after is not None:
            st.caption(f"After: {format_inr(d.cash_after)}")

    st.markdown("</div>", unsafe_allow_html=True)


def _render_waterfall(result: AnalysisResult) -> None:
    """
    Show cash balance after each PAY_NOW transaction.
    Deterministic — uses cash_after from optimizer output.
    """
    from core.config import MIN_CASH_BUFFER

    pay_now = [
        d for d in result.payments.decisions
        if d.action == "PAY_NOW"
    ]

    if not pay_now:
        st.caption("No PAY_NOW transactions in current plan.")
        return

    approx_start = result.payments.spendable_now + MIN_CASH_BUFFER

    rows = [f"**Start:** {format_inr(approx_start)}"]
    for d in pay_now:
        rows.append(
            f"→ Pay **{d.payee}** {format_inr(d.amount)} "
            f"= **{format_inr(d.cash_after)}** remaining"
        )
    rows.append(
        f"\n**Buffer protected:** {format_inr(MIN_CASH_BUFFER)} "
        f"minimum always reserved."
    )

    st.markdown("  \n".join(rows))

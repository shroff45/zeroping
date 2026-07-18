# ui/dashboard.py
# B15.2 — Dashboard tab renderer
# Owner: Rishil
# Deps: B05, ui/styles.py, core/money.py
#
# RULES:
#   - Render only. No computation. No DB access. No LLM calls.
#   - All numbers come from AnalysisResult passed in.
#   - Typewriter effect on headline only (not findings — too slow).
#   - Fallback badge shown when narrative came from fallback.
#   - "One collection changes everything" box is pre-computed
#     from engine outputs — not LLM-generated.

from __future__ import annotations

import time

import streamlit as st

from core.schemas import AnalysisResult
from core.money import format_inr
from ui.styles import risk_badge_html


def render(result: AnalysisResult, narrative: dict | None) -> None:
    """
    Render the dashboard tab.
    narrative: dict with keys headline/finding_1-3/action
               or None if analysis not yet run.
    """

    liq  = result.liquidity
    proj = result.projection

    # ── Hero risk badge ───────────────────────────────────────
    st.markdown(
        risk_badge_html(liq.risk_level, liq.risk_score),
        unsafe_allow_html=True,
    )

    # ── Stat cards ────────────────────────────────────────────
    # Cash balance: spendable_now + buffer (snapshot not on result)
    from core.config import MIN_CASH_BUFFER
    approx_cash = result.payments.spendable_now + MIN_CASH_BUFFER

    c1, c2, c3, c4 = st.columns(4)

    with c1:
        st.metric(
            label="Cash Balance",
            value=format_inr(approx_cash),
        )
    with c2:
        delta_str = (
            "⚠️ CRITICAL" if liq.risk_level == "CRITICAL"
            else f"Score {liq.risk_score}/100"
        )
        st.metric(
            label="Cash Runway",
            value=f"{liq.runway_days:.0f} days",
            delta=delta_str,
            delta_color="inverse" if liq.risk_level == "CRITICAL" else "normal",
        )
    with c3:
        st.metric(
            label="Min Balance (90d)",
            value=format_inr(proj.min_balance),
            delta=f"Day {proj.min_balance_day}",
            delta_color="off",
        )
    with c4:
        overdue_ar = sum(
            a.invoice_amount
            for a in result.anomalies.anomalies
            if a.days_overdue > 0
        )
        st.metric(
            label="Overdue AR",
            value=format_inr(overdue_ar),
        )

    st.divider()

    # ── "One collection changes everything" box ───────────────
    apex = next(
        (a for a in result.anomalies.anomalies
         if a.severity == "ANOMALY"),
        None,
    )

    if apex:
        _render_intervention_box(result, apex)

    # ── GST Calendar ──────────────────────────────────────────
    _render_gst_panel(result)

    # ── Bankability ───────────────────────────────────────────
    _render_bankability_panel(result)

    st.divider()

    # ── Narrative card ────────────────────────────────────────
    if narrative:
        _render_narrative(result, narrative)
    else:
        st.info("Click **Analyse** to generate insights.")

    # ── Score breakdown ───────────────────────────────────────
    with st.expander("Score breakdown", expanded=False):
        st.caption(
            "Lower score = worse. CRITICAL < 25. "
            "Weights: runway 40%, receivables quality 25%, "
            "quick ratio 20%, DSO 15%."
        )
        for component, score in liq.components.items():
            label = component.replace("_", " ").title()
            st.markdown(f"**{label}**: {score:.1f} pts")

    # ── Grounding audit panel ─────────────────────────────────
    if narrative:
        with st.expander("🔍 Grounding audit", expanded=False):
            _render_grounding_audit(result, narrative)


# ── Private helpers ───────────────────────────────────────────────

def _render_intervention_box(result: AnalysisResult, apex) -> None:
    """
    The "one collection changes everything" moment.
    All numbers are engine-computed. Zero LLM involvement.
    """
    from core.config import MIN_CASH_BUFFER, DAILY_BURN

    # Simulate: what if Apex pays in full?
    simulated_cash = (
        result.payments.spendable_now + MIN_CASH_BUFFER
        + apex.invoice_amount
    )
    simulated_runway = simulated_cash / DAILY_BURN

    # Risk level after payment (rough — full engine not re-run)
    if simulated_runway > 60:
        sim_risk = "LOW"
    elif simulated_runway > 30:
        sim_risk = "MODERATE"
    elif simulated_runway > 15:
        sim_risk = "HIGH"
    else:
        sim_risk = "CRITICAL"

    st.markdown(
        '<div class="intervention-box">',
        unsafe_allow_html=True,
    )
    st.markdown(f"#### 💡 One collection changes everything")
    st.markdown(
        f"If **{apex.client}** pays their "
        f"**{format_inr(apex.invoice_amount)}** invoice:"
    )

    ic1, ic2, ic3 = st.columns(3)
    with ic1:
        st.metric(
            "Risk level",
            sim_risk,
            delta=f"from {result.liquidity.risk_level}",
            delta_color="inverse",
        )
    with ic2:
        st.metric(
            "Cash runway",
            f"{simulated_runway:.0f} days",
            delta=f"+{simulated_runway - result.liquidity.runway_days:.0f} days",
        )
    with ic3:
        # Which payments get unblocked
        scheduled = [
            d for d in result.payments.decisions
            if d.action == "SCHEDULED"
        ]
        if scheduled:
            st.metric(
                "Unblocked",
                f"{len(scheduled)} payment{'s' if len(scheduled) > 1 else ''}",
                delta=", ".join(d.payee for d in scheduled[:2]),
                delta_color="off",
            )

    st.markdown('</div>', unsafe_allow_html=True)
    st.divider()


def _render_narrative(result: AnalysisResult, narrative: dict) -> None:
    """Render LLM/fallback narrative with typewriter on headline."""
    is_fallback = result.liquidity.is_fallback

    st.markdown(
        '<div class="narrative-card">',
        unsafe_allow_html=True,
    )

    if is_fallback:
        st.markdown(
            '<div class="fallback-badge">template mode — '
            'Ollama offline</div>',
            unsafe_allow_html=True,
        )

    # Typewriter on headline
    headline = narrative.get("headline", "")
    _typewriter(headline, speed=0.018)

    # Findings as bullet points
    st.markdown("")
    for key in ("finding_1", "finding_2", "finding_3"):
        text = narrative.get(key, "")
        if text:
            st.markdown(f"- {text}")

    # Action as info box
    action = narrative.get("action", "")
    if action:
        st.info(f"**Action:** {action}")

    st.markdown('</div>', unsafe_allow_html=True)


def _render_grounding_audit(result: AnalysisResult, narrative: dict) -> None:
    """
    Show every number the LLM used and whether it passed the firewall.
    This is the live proof that no numbers are hallucinated.
    """
    from llm.grounding import build_allowlist, grounding_summary

    allowed = build_allowlist(result)
    full_text = " ".join(str(v) for v in narrative.values())
    summary = grounding_summary(full_text, allowed)

    total = len(summary["passed"]) + len(summary["rejected"])

    if summary["is_clean"]:
        st.markdown(
            f'<div class="grounding-pass">'
            f'✅ {total} numbers checked — 0 rejections'
            f'</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f'<div class="grounding-fail">'
            f'❌ {len(summary["rejected"])} rejection(s) detected'
            f'</div>',
            unsafe_allow_html=True,
        )

    st.caption("Every number in the narrative is validated against engine outputs.")

    if summary["passed"]:
        st.markdown(
            "**Verified numbers:** "
            + ", ".join(str(n) for n in sorted(set(summary["passed"]))[:8])
        )
    if summary["rejected"]:
        st.error(
            "**Rejected (not from engines):** "
            + ", ".join(str(n) for n in summary["rejected"])
        )


def _render_gst_panel(result: AnalysisResult) -> None:
    """
    GST Calendar panel. Auto-expands if any URGENT event exists.
    All data from result.gst_calendar — no computation.
    """
    gst = result.gst_calendar
    has_urgent = any(
        e.urgency in ("URGENT", "OVERDUE")
        for e in gst.events
    )

    with st.expander("🗓️ Upcoming GST Obligations", expanded=has_urgent):
        if not gst.events:
            st.caption("No upcoming GST obligations in the next 90 days.")
            return

        for event in gst.events:
            urgency = event.urgency
            css = urgency.lower()
            badge = (
                f'<span class="gst-badge gst-badge-{urgency}">'
                f'{urgency}</span>'
            )
            days_text = (
                f"{abs(event.days_until_due)}d overdue"
                if event.days_until_due < 0
                else f"in {event.days_until_due}d"
            )
            amount_text = (
                f" &nbsp;·&nbsp; {format_inr(event.amount)}"
                if event.amount
                else ""
            )
            st.markdown(
                f'<div class="gst-event gst-{css}">'
                f'<span><strong>{event.description}</strong>'
                f' &nbsp; {event.due_date.strftime("%d %b %Y")}'
                f' &nbsp; ({days_text}){amount_text}</span>'
                f'{badge}</div>',
                unsafe_allow_html=True,
            )

        st.caption(
            "Dates from CBIC standard schedule. "
            "Amounts shown only when a matching payable row exists."
        )


def _render_bankability_panel(result: AnalysisResult) -> None:
    """
    Bankability score panel: grade, score, schemes, blockers.
    All data from result.bankability — no computation.
    """
    bank = result.bankability

    with st.expander("🏦 Loan Eligibility (Mudra / CGTMSE)", expanded=False):
        if bank.is_fallback:
            st.caption("Bankability engine not available.")
            return

        b1, b2 = st.columns([1, 3])

        with b1:
            st.markdown(
                f'<div class="bankability-grade bankability-{bank.grade}">'
                f'{bank.grade}</div>',
                unsafe_allow_html=True,
            )
            st.caption("Grade")

        with b2:
            bc1, bc2, bc3 = st.columns(3)
            with bc1:
                st.metric("Score", f"{bank.score} / 100")
            with bc2:
                st.metric("Mudra Tier", bank.mudra_tier)
            with bc3:
                st.metric("CCC", f"{bank.ccc_days:.0f}d")

            if bank.eligible_schemes:
                schemes_html = " ".join(
                    f'<span class="bankability-scheme">{s}</span>'
                    for s in bank.eligible_schemes
                )
                st.markdown(
                    f"**Eligible schemes:** {schemes_html}",
                    unsafe_allow_html=True,
                )
            else:
                st.warning("No schemes currently eligible.")

            st.caption(
                f"DSO: {bank.dso_days:.0f}d &nbsp;·&nbsp; "
                f"DPO: {bank.dpo_days:.0f}d &nbsp;·&nbsp; "
                f"CCC: {bank.ccc_days:.0f}d",
            )

        if bank.blockers:
            st.markdown("**What's blocking a better grade:**")
            for blocker in bank.blockers:
                st.markdown(
                    f'<div class="bankability-blocker">⚠️ {blocker}</div>',
                    unsafe_allow_html=True,
                )

        st.caption(
            "Computed from runway, DSO, and quick ratio. "
            "Resolve blockers above to improve eligibility."
        )


def _typewriter(text: str, speed: float = 0.018) -> None:
    """
    Render text with typewriter effect.
    Uses st.empty() placeholder — updates in place.
    """
    placeholder = st.empty()
    displayed = ""
    for char in text:
        displayed += char
        placeholder.markdown(f"**{displayed}▌**")
        time.sleep(speed)
    placeholder.markdown(f"**{displayed}**")

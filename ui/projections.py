# ui/projections.py
# B15.4 — Projections tab renderer
# Owner: Rishil
# Deps: B05, core/money.py
#
# RULES:
#   - Render only. No computation. No DB. No LLM.
#   - Plotly chart built from pre-computed engine arrays.
#   - Crossover annotation always shown if crossover_day exists.
#   - Band caption explains WHY it widens (judge answer built in).
#   - Excluded receivables shown as caption, not error.
#   - All monetary values formatted with format_inr.

from __future__ import annotations

import streamlit as st
import plotly.graph_objects as go

from core.schemas import AnalysisResult, CompanySnapshot
from core.money import format_inr
from core.config import DEMO_DATE


def render(result: AnalysisResult, snap: CompanySnapshot) -> None:
    """Render the projections tab. snap needed for What-If engine."""

    proj = result.projection

    # ── Alert banner ──────────────────────────────────────────
    if proj.crossover_day is not None:
        st.error(
            f"⚠️ **Cash out projected: Day {proj.crossover_day}** "
            f"({_day_to_date(proj.crossover_day)}) — "
            f"act before this date."
        )
    else:
        st.success("No cash crossover within 90 days under baseline.")

    # ── Excluded receivables notice ───────────────────────────
    if proj.excluded_receivables:
        excluded_names = ", ".join(proj.excluded_receivables)
        st.caption(
            f"⚠️ Excluded from baseline (anomalous — cannot be relied on): "
            f"**{excluded_names}**. "
            f"Baseline is conservative."
        )

    # ── Plotly chart ──────────────────────────────────────────
    fig = _build_chart(proj)
    st.plotly_chart(fig, use_container_width=True)

    # ── Band explanation ──────────────────────────────────────
    st.caption(
        "Band is a t-based **prediction interval** (df=4, n=6 months). "
        "It widens with horizon — six months of data does not buy a "
        "clean estimate at Day 90. "
        "We show the honest range rather than a false precision line."
    )

    # ── 30 / 60 / 90 day readout ──────────────────────────────
    st.divider()
    c1, c2, c3 = st.columns(3)

    with c1:
        _day_metric("Day 30", proj.day30, proj, 29)
    with c2:
        _day_metric("Day 60", proj.day60, proj, 59)
    with c3:
        _day_metric("Day 90", proj.day90, proj, 89)

    # ── What-If Scenario ──────────────────────────────────────
    _render_what_if(result, snap)

    # ── Daily ledger detail ───────────────────────────────────
    with st.expander("Daily ledger detail (first 30 days)", expanded=False):
        _render_daily_table(proj)


# ── Private helpers ───────────────────────────────────────────────

def _build_chart(proj) -> go.Figure:
    """Build the Plotly cash flow projection chart."""

    days = list(range(90))

    fig = go.Figure()

    # Prediction band (fill between lower and upper)
    fig.add_trace(go.Scatter(
        x=days + days[::-1],
        y=list(proj.daily_upper) + list(proj.daily_lower)[::-1],
        fill="toself",
        fillcolor="rgba(56,189,248,0.12)",
        line=dict(color="rgba(0,0,0,0)"),
        name="Prediction band (95%)",
        hoverinfo="skip",
    ))

    # Upper bound line (subtle)
    fig.add_trace(go.Scatter(
        x=days,
        y=list(proj.daily_upper),
        line=dict(color="rgba(56,189,248,0.3)", width=1, dash="dot"),
        name="Upper bound",
        hoverinfo="skip",
    ))

    # Lower bound line (subtle)
    fig.add_trace(go.Scatter(
        x=days,
        y=list(proj.daily_lower),
        line=dict(color="rgba(56,189,248,0.3)", width=1, dash="dot"),
        name="Lower bound",
        hoverinfo="skip",
    ))

    # Expected balance line (primary)
    fig.add_trace(go.Scatter(
        x=days,
        y=list(proj.daily_expected),
        line=dict(color="#38BDF8", width=2.5),
        name="Expected balance",
        hovertemplate=(
            "Day %{x}<br>"
            "Balance: ₹%{y:,.0f}<extra></extra>"
        ),
    ))

    # Zero line
    fig.add_hline(
        y=0,
        line_color="#EF4444",
        line_width=1.5,
        line_dash="dot",
        annotation_text="Zero",
        annotation_position="right",
        annotation_font_color="#EF4444",
    )

    # Crossover annotation
    if proj.crossover_day is not None and proj.crossover_day < 90:
        fig.add_vline(
            x=proj.crossover_day,
            line_color="#EF4444",
            line_width=2,
            line_dash="dash",
            annotation_text=f"⚠️ Day {proj.crossover_day}",
            annotation_position="top left",
            annotation_font_color="#EF4444",
            annotation_font_size=13,
        )

    # Min balance annotation
    if 0 <= proj.min_balance_day < 90:
        fig.add_annotation(
            x=proj.min_balance_day,
            y=proj.min_balance,
            text=f"Min {format_inr(proj.min_balance)}",
            showarrow=True,
            arrowhead=2,
            arrowcolor="#F59E0B",
            font=dict(color="#F59E0B", size=11),
            bgcolor="#1E293B",
            bordercolor="#F59E0B",
        )

    fig.update_layout(
        paper_bgcolor="#0F172A",
        plot_bgcolor="#0F172A",
        font_color="#E2E8F0",
        xaxis=dict(
            title="Days from today",
            gridcolor="#1E293B",
            zerolinecolor="#334155",
            tickfont=dict(size=11),
        ),
        yaxis=dict(
            title="Cash Balance (₹)",
            gridcolor="#1E293B",
            zerolinecolor="#334155",
            tickformat=",",
            tickfont=dict(size=11),
        ),
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            font=dict(size=11),
        ),
        margin=dict(l=20, r=20, t=30, b=20),
        height=420,
        hovermode="x unified",
    )

    return fig


def _day_metric(
    label: str,
    value: float,
    proj,
    day_idx: int,
) -> None:
    """Render a single day-N metric card with uncertainty range."""
    lower = proj.daily_lower[day_idx]
    upper = proj.daily_upper[day_idx]

    st.metric(
        label=label,
        value=format_inr(value),
        delta=None,
    )
    st.caption(
        f"Range: {format_inr(lower)} → {format_inr(upper)}"
    )


def _render_daily_table(proj) -> None:
    """Show first 30 days as a simple markdown table."""
    rows = ["| Day | Expected | Lower | Upper |",
            "|-----|----------|-------|-------|"]

    for i in range(30):
        exp   = format_inr(proj.daily_expected[i])
        lower = format_inr(proj.daily_lower[i])
        upper = format_inr(proj.daily_upper[i])
        rows.append(f"| {i:02d}  | {exp} | {lower} | {upper} |")

    st.markdown("\n".join(rows))


def _day_to_date(day_offset: int) -> str:
    """Convert day offset to readable date string."""
    from datetime import timedelta
    target = DEMO_DATE + timedelta(days=day_offset)
    return target.strftime("%b %d")


def _render_what_if(result: AnalysisResult, snap: CompanySnapshot) -> None:
    """
    What-If Scenario panel.
    Selectbox populated from anomalous clients only.
    On button press: re-runs engines on a mutated snapshot copy.
    Result displayed inline — no page reload.
    All computation in engine/what_if.py, not here.
    """
    st.divider()
    st.markdown("#### 💡 What-If Scenario")
    st.caption(
        "Select a flagged client and simulate their invoice being paid today. "
        "Engines re-run on a copy of the snapshot — no data is saved."
    )

    # Only show anomalous clients (the interesting ones)
    anomalous = [
        a.client
        for a in result.anomalies.anomalies
        if a.severity == "ANOMALY"
    ]

    if not anomalous:
        st.caption("No anomalous clients to simulate. All AR looks normal.")
        return

    selected_client = st.selectbox(
        "Choose client to simulate payment",
        options=anomalous,
        key="whatif_client_select",
    )

    run_btn = st.button(
        "▶ Run scenario",
        type="primary",
        key="whatif_run",
    )

    if run_btn and selected_client:
        from engine.what_if import what_if_scenario
        with st.spinner(f"Simulating {selected_client} payment..."):
            wif = what_if_scenario(snap, selected_client)

        st.markdown(
            '<div class="whatif-result-box">',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div class="whatif-label">{wif.scenario_label}</div>',
            unsafe_allow_html=True,
        )

        wc1, wc2, wc3 = st.columns(3)
        with wc1:
            st.metric(
                "Cash Gained",
                format_inr(wif.delta_cash),
                delta="immediate",
                delta_color="normal",
            )
        with wc2:
            crossover_label = (
                f"Day {wif.new_crossover_day}"
                if wif.new_crossover_day
                else "None in 90d"
            )
            old_crossover = result.projection.crossover_day
            crossover_delta = (
                f"was Day {old_crossover}" if old_crossover else ""
            )
            st.metric(
                "Crossover",
                crossover_label,
                delta=crossover_delta,
                delta_color="off",
            )
        with wc3:
            st.metric(
                "Risk Level After",
                wif.new_risk_level,
                delta=f"was {result.liquidity.risk_level}",
                delta_color=(
                    "normal"
                    if wif.new_risk_level != result.liquidity.risk_level
                    else "off"
                ),
            )

        if wif.payments_unlocked:
            st.success(
                "🟢 Payments unlocked: "
                + ", ".join(wif.payments_unlocked)
            )

        st.markdown("</div>", unsafe_allow_html=True)
        st.caption(
            "Simulation only. No database write. "
            "Engines re-run deterministically on modified snapshot."
        )


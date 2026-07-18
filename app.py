# app.py
# B14 — Main Streamlit entry point
# Owner: Rishil
# Deps: All phases
#
# SESSION STATE: exactly 3 keys (PRD)
#   result     — AnalysisResult | None
#   narratives — dict[str, dict]  (dashboard, email_*, ask_gemma_log)
#   running    — bool
#
# LLM:
#   Cache-first. Fallback always available.
#   Regenerate bypasses cache.
#   Ask Gemma is agentically grounded.
#
# RULES:
#   - No st.experimental_* anything
#   - No threading
#   - Every user action is idempotent under rapid clicking
#   - snapshot embedded in result — no 4th session state key

from __future__ import annotations

import json

import streamlit as st

from core.db import get_session, reset_to_golden
from core.repository import load_snapshot
from core.pipeline import run_pipeline
from llm.backend import OllamaBackend
from llm.cache import cache_key, get as cache_get, put as cache_put, clear as cache_clear
from llm.grounding import build_allowlist, is_grounded
from llm.prompts import dashboard_messages, email_messages, SCHEMA_DASHBOARD, SCHEMA_EMAIL
from llm.fallbacks import dashboard_fallback, email_fallback
from ui.styles import inject_styles, risk_badge_html
from ui.upload import render_upload_panel

# ── Page config (must be first Streamlit call) ────────────────────────
st.set_page_config(
    page_title="LedgeAI",
    page_icon="💎",
    layout="wide",
    initial_sidebar_state="expanded",
)
inject_styles()

# ── Session state: exactly 3 keys ─────────────────────────────────────
if "result"     not in st.session_state:
    st.session_state.result     = None
if "narratives" not in st.session_state:
    st.session_state.narratives = {}
if "running"    not in st.session_state:
    st.session_state.running    = False


# ── LLM backend (cached resource — one instance per session) ──────────
@st.cache_resource(show_spinner=False)
def _get_llm() -> OllamaBackend:
    return OllamaBackend()


llm     = _get_llm()
healthy = llm.health()


# ── LLM generation helper ─────────────────────────────────────────────
def _generate_narrative(
    result,
    prompt_kind: str,
    messages: list[dict],
    fallback_fn,
    bypass: bool = False,
    **fallback_kwargs,
) -> dict:
    """
    Cache-first narrative generation.
    1. Check cache (skip if bypass=True)
    2. Call Ollama if cache miss and healthy
    3. Validate grounding (bifurcated tolerance)
    4. Store in cache if valid
    5. Always return a dict — fallback if anything fails

    fallback_fn signature:
      dashboard: fallback_fn(result) → dict
      email:     fallback_fn(result, client_name) → dict
    """
    key    = cache_key(result.snapshot_hash, prompt_kind)
    cached = cache_get(key, bypass_cache=bypass)

    if cached:
        try:
            return json.loads(cached)
        except Exception:
            pass

    if healthy and messages:
        schema = SCHEMA_DASHBOARD if prompt_kind == "dashboard" else SCHEMA_EMAIL
        raw    = llm.generate(messages, schema=schema)
        if raw:
            allowed = build_allowlist(result)
            ok, _   = is_grounded(raw, allowed)
            if ok:
                try:
                    parsed = json.loads(raw)
                    cache_put(key, raw)
                    return parsed
                except Exception:
                    pass

    # Fallback — always works, pre-verified
    if fallback_kwargs:
        return fallback_fn(result, **fallback_kwargs)
    return fallback_fn(result)


# ── Sidebar ───────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 💎 LedgeAI")
    st.caption("Privacy-first cashflow copilot for Indian SMEs.")
    st.divider()

    # Health indicator
    if healthy:
        st.markdown("🟢 **On-device AI ready**")
        st.caption(f"Model: `{llm.model}`")
    else:
        st.markdown("🔴 **AI offline — cache mode**")
        st.caption("Narratives from pre-verified templates.")

    st.divider()

    # Analyse button
    analyse_clicked = st.button(
        "🔍 Analyse",
        type="primary",
        disabled=st.session_state.running,
        use_container_width=True,
        key="btn_analyse",
    )

    # Regenerate button (only when result exists and LLM healthy)
    regen_clicked = False
    if st.session_state.result and healthy:
        regen_clicked = st.button(
            "↻ Regenerate live",
            use_container_width=True,
            key="btn_regen",
        )

    # Reset button
    reset_clicked = st.button(
        "🔄 Reset demo data",
        use_container_width=True,
        key="btn_reset",
    )

    st.divider()

    # ── Ask Gemma (agentic) ───────────────────────────────────────
    if st.session_state.result is not None:
        st.markdown("#### 🤖 Ask Gemma")
        user_query = st.text_input(
            "Ask about your finances",
            key="ask_gemma_input",
            placeholder="What is my cash runway?",
            label_visibility="collapsed",
        )
        ask_clicked = st.button(
            "Ask",
            key="btn_ask_gemma",
            use_container_width=True,
        )

        if ask_clicked and user_query.strip():
            from llm.agentic_backend import AgenticBackend
            result = st.session_state.result
            agent  = AgenticBackend(llm=llm, result=result)
            answer, tool_log = agent.ask(user_query.strip())

            # Store in narratives (not a 4th key — narratives is key 2)
            narr = st.session_state.narratives
            narr["ask_gemma_answer"]   = answer
            narr["ask_gemma_query"]    = user_query.strip()
            narr["ask_gemma_tool_log"] = tool_log
            st.session_state.narratives = narr

        # Display answer and tool call log (G31)
        narr = st.session_state.narratives
        if narr.get("ask_gemma_answer"):
            st.markdown(f"**Q:** {narr['ask_gemma_query']}")
            st.markdown(narr["ask_gemma_answer"])

            tool_log = narr.get("ask_gemma_tool_log", [])
            if tool_log:
                with st.expander("🔧 Tool calls", expanded=False):
                    for tc in tool_log:
                        st.caption(f"Called: `{tc['tool']}`")
                        st.json(tc.get("result", {}), expanded=False)

    st.divider()

    # ── Bank Statement Upload ─────────────────────────────────
    render_upload_panel(location="sidebar")

    st.divider()

    # Cache stats
    from llm.cache import stats as cache_stats
    s = cache_stats()
    st.caption(f"Cache: {s['entries']} entries")


# ── Button handlers ───────────────────────────────────────────────────

if reset_clicked:
    cache_clear()
    reset_to_golden()
    st.session_state.result     = None
    st.session_state.narratives = {}
    st.session_state.running    = False
    st.rerun()

if analyse_clicked and not st.session_state.running:
    st.session_state.running = True

    with st.spinner("Analysing your ledger..."):
        with get_session() as sess:
            snap = load_snapshot(sess)
        result = run_pipeline(snap)
        st.session_state.result = result

        # Dashboard narrative (cache-first)
        narr = _generate_narrative(
            result,
            prompt_kind="dashboard",
            messages=dashboard_messages(result),
            fallback_fn=dashboard_fallback,
        )
        st.session_state.narratives["dashboard"] = narr

    st.session_state.running = False
    st.rerun()

if regen_clicked and st.session_state.result:
    result = st.session_state.result
    narr   = _generate_narrative(
        result,
        prompt_kind="dashboard",
        messages=dashboard_messages(result),
        fallback_fn=dashboard_fallback,
        bypass=True,
    )
    st.session_state.narratives["dashboard"] = narr
    st.rerun()


# ── Main content ──────────────────────────────────────────────────────

if st.session_state.result is None:
    # Landing state
    st.markdown("## 💎 LedgeAI")
    st.markdown(
        "**Privacy-first AI cashflow copilot for Indian SMEs.**  \n"
        "Your books never leave this device.  \n\n"
        "← Click **Analyse** to begin."
    )
    st.divider()
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("#### 🔍 Detect")
        st.caption("Anomalous payment patterns flagged before they become crises.")
    with col2:
        st.markdown("#### 📈 Project")
        st.caption("90-day cash flow with honest uncertainty bands.")
    with col3:
        st.markdown("#### ✉️ Act")
        st.caption("Collection emails and payment plans in one click.")

else:
    result = st.session_state.result
    narr   = st.session_state.narratives

    # Import tab modules (avoids circular import at module level)
    from ui import dashboard, invoices, projections, payments, upload

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 Dashboard",
        "📋 Invoices",
        "📈 Projections",
        "💳 Payments",
        "📂 Data",
    ])

    with tab1:
        dashboard.render(result, narr.get("dashboard"))
    with tab2:
        invoices.render(result, llm, narr, healthy)
    with tab3:
        projections.render(result, result.snapshot)
    with tab4:
        payments.render(result)
    with tab5:
        st.markdown("### 📂 Data Ingestion")
        st.markdown("Import your bank statement or receivables CSV to update the ledger.")
        st.divider()

        data_col1, data_col2 = st.columns(2)
        with data_col1:
            upload.render_upload_panel(location="tab")
        with data_col2:
            st.markdown("### 📄 Receivables CSV")
            csv_up = st.file_uploader(
                "Upload receivables CSV",
                type=["csv"],
                key="csv_receivables_upload",
                label_visibility="collapsed",
                help="Columns: client, amount, date, terms_days (optional)",
            )
            if csv_up is not None:
                from data.csv_import import parse_csv, import_to_db
                rows, csv_errors = parse_csv(csv_up)
                for e in csv_errors:
                    st.warning(e)
                if rows:
                    st.success(f"Parsed {len(rows)} receivable rows.")
                    import pandas as pd
                    from core.money import format_inr
                    preview = pd.DataFrame([
                        {
                            "Client":     r["client"],
                            "Amount":     format_inr(r["amount"]),
                            "Date":       str(r["issue_date"]),
                            "Terms (d)":  r["terms_days"],
                        }
                        for r in rows
                    ])
                    st.dataframe(preview, use_container_width=True, hide_index=True)
                    if st.button("✅ Import to Ledger", key="btn_csv_import", type="primary"):
                        with get_session() as sess:
                            inserted, db_errs = import_to_db(sess, rows)
                        for e in db_errs:
                            st.error(e)
                        if not db_errs:
                            st.success(f"Imported {inserted} receivables.")
                            st.session_state.result     = None
                            st.session_state.narratives = {}
                            st.info("← Click Analyse to refresh.")

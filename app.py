# app.py
# B14 — Main Streamlit entry point
# Owner: Rishil
# Deps: All phases
#
# RULES:
#   - 3 session state keys only: result, narratives, running
#   - LLM is cache-first. Fallback is always available.
#   - Regenerate button bypasses cache (bypass_cache=True)
#   - Reset button: clear cache + restore golden.db + st.rerun()
#   - No st.experimental_* anything
#   - No threading
#   - Every user action is idempotent under rapid clicking

from __future__ import annotations

import json

import streamlit as st

from core.db import get_session, reset_to_golden
from core.repository import load_snapshot
from core.pipeline import run_pipeline
from llm.backend import OllamaBackend
from llm.cache import cache_key, get as cache_get, put as cache_put, clear as cache_clear
from llm.grounding import build_allowlist, is_grounded
from llm.prompts import dashboard_messages, email_messages
from llm.fallbacks import dashboard_fallback, email_fallback
from ui.styles import inject_styles, risk_badge_html

# ── Page config (must be first Streamlit call) ────────────────────
st.set_page_config(
    page_title="LedgeAI",
    page_icon="💎",
    layout="wide",
    initial_sidebar_state="expanded",
)
inject_styles()

# ── Session state (3 keys only) ───────────────────────────────────
if "result"     not in st.session_state:
    st.session_state.result     = None
if "snap"       not in st.session_state:
    st.session_state.snap       = None
if "narratives" not in st.session_state:
    st.session_state.narratives = {}
if "running"    not in st.session_state:
    st.session_state.running    = False


# ── LLM backend (cached resource — one instance per session) ──────
@st.cache_resource(show_spinner=False)
def _get_llm() -> OllamaBackend:
    return OllamaBackend()


llm     = _get_llm()
healthy = llm.health()


# ── LLM generation helper (used by sidebar + invoices tab) ────────
def _generate_narrative(
    result,
    prompt_kind: str,
    messages: list[dict],
    fallback_fn,
    bypass: bool = False,
) -> dict:
    """
    Cache-first narrative generation.
    1. Check cache (skip if bypass=True)
    2. Call Ollama if cache miss and healthy
    3. Validate grounding
    4. Store in cache if valid
    5. Always return a dict — fallback if anything fails
    """
    key = cache_key(result.snapshot_hash, prompt_kind)
    cached = cache_get(key, bypass_cache=bypass)

    if cached:
        try:
            return json.loads(cached)
        except Exception:
            pass

    if healthy and messages:
        from llm.prompts import SCHEMA_DASHBOARD, SCHEMA_EMAIL
        schema = (
            SCHEMA_DASHBOARD
            if prompt_kind == "dashboard"
            else SCHEMA_EMAIL
        )
        raw = llm.generate(messages, schema=schema)
        if raw:
            allowed = build_allowlist(result)
            ok, _ = is_grounded(raw, allowed)
            if ok:
                try:
                    parsed = json.loads(raw)
                    cache_put(key, raw)
                    return parsed
                except Exception:
                    pass

    return fallback_fn(result) if prompt_kind == "dashboard" else fallback_fn


# ── Sidebar ───────────────────────────────────────────────────────
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

    # Cache stats
    from llm.cache import stats as cache_stats
    s = cache_stats()
    st.caption(f"Cache: {s['entries']} entries")


# ── Button handlers ───────────────────────────────────────────────

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
        st.session_state.snap   = snap

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
    narr = _generate_narrative(
        result,
        prompt_kind="dashboard",
        messages=dashboard_messages(result),
        fallback_fn=dashboard_fallback,
        bypass=True,
    )
    st.session_state.narratives["dashboard"] = narr
    st.rerun()

# ── Main content ──────────────────────────────────────────────────

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

    # Import tab modules here (avoids circular import at module level)
    from ui import dashboard, invoices, projections, payments

    tab1, tab2, tab3, tab4 = st.tabs([
        "📊 Dashboard",
        "📋 Invoices",
        "📈 Projections",
        "💳 Payments",
    ])

    with tab1:
        dashboard.render(result, narr.get("dashboard"))
    with tab2:
        invoices.render(result, llm, narr, healthy)
    with tab3:
        projections.render(result, st.session_state.snap)
    with tab4:
        payments.render(result)

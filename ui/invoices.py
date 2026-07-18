# ui/invoices.py
# B15.3 — Invoices tab renderer
# Owner: Rishil
# Deps: B05, ui/styles.py, core/money.py, llm/*
#
# RULES:
#   - Render only. No pipeline calls.
#   - Email generation triggered by button click only.
#   - Email stored in st.session_state.narratives keyed by client.
#   - Grounding check runs on every LLM response before display.
#   - Fallback email always available — never shows blank.
#   - WhatsApp: wa.me deep link — offline friendly, no API key.
#   - Bank statement upload: handled in ui/sidebar.py via st.file_uploader.

from __future__ import annotations

import json
import urllib.parse

import streamlit as st

from core.schemas import AnalysisResult
from core.money import format_inr
from llm.backend import OllamaBackend
from llm.cache import cache_key, get as cache_get, put as cache_put
from llm.grounding import build_allowlist, is_grounded
from llm.prompts import email_messages, SCHEMA_EMAIL
from llm.fallbacks import email_fallback


def render(
    result: AnalysisResult,
    llm: OllamaBackend,
    narr: dict,
    healthy: bool,
) -> None:
    """
    Render the invoices tab.

    narr: shared narratives dict from session state.
          Keys: f'email_{client_name}' → email dict
    healthy: whether Ollama is reachable.
    """

    anomalies = result.anomalies.anomalies

    if not anomalies:
        st.info("No open invoices to display.")
        return

    st.markdown("### Open Invoice Status")
    st.caption(
        "Anomaly detection uses t-score (student's t, df = n − 1) against each client's "
        "payment history. † = still unpaid, t understates true delay."
    )

    for anom in anomalies:
        _render_invoice_row(result, llm, narr, healthy, anom)


# ── Private helpers ───────────────────────────────────────────────

def _render_invoice_row(result, llm, narr, healthy, anom) -> None:
    """Render one invoice row + optional email panel."""

    severity = anom.severity
    client   = anom.client

    # ── Severity row ──────────────────────────────────────────
    st.markdown(
        f'<div class="severity-row severity-{severity}">',
        unsafe_allow_html=True,
    )

    col1, col2, col3 = st.columns([4, 2, 1])

    with col1:
        icon = {"ANOMALY": "🔴", "WATCH": "🟡", "NORMAL": "🟢"}[severity]
        st.markdown(f"**{icon} {client}**")

        parts = [f"{anom.days_since_issue}d since issue"]
        if anom.days_overdue > 0:
            parts.append(f"{anom.days_overdue}d overdue")
        if anom.censored:
            parts.append("† t understates (still unpaid)")
        st.caption(" · ".join(parts))

    with col2:
        st.markdown(f"**{format_inr(anom.invoice_amount)}**")
        if anom.t_score > 0 and anom.std_days > 0:
            st.caption(
                f"t={anom.t_score:.1f} · "
                f"threshold {anom.t_anomaly:.2f} · "
                f"avg {anom.mean_days:.0f}d"
            )

    with col3:
        st.markdown(f"**{severity}**")

    st.markdown("</div>", unsafe_allow_html=True)

    # ── Email panel (ANOMALY only) ────────────────────────────
    if severity == "ANOMALY":
        email_key = f"email_{client}"
        email_data = narr.get(email_key)

        btn_label = (
            "✉️ Regenerate email"
            if email_data
            else "✉️ Draft collection email"
        )

        if st.button(
            btn_label,
            key=f"btn_{email_key}",
            type="primary" if not email_data else "secondary",
        ):
            email_data = _generate_email(result, llm, healthy, client)
            narr[email_key] = email_data
            st.session_state.narratives = narr
            st.rerun()

        if email_data:
            _render_email_panel(email_data, client)


def _generate_email(
    result: AnalysisResult,
    llm: OllamaBackend,
    healthy: bool,
    client_name: str,
) -> dict:
    """
    Generate or retrieve cached collection email.
    Always returns a valid dict — fallback if anything fails.
    """
    key = cache_key(result.snapshot_hash, f"email_{client_name}")

    # Cache check
    cached = cache_get(key)
    if cached:
        try:
            return json.loads(cached)
        except Exception:
            pass

    # Live generation
    if healthy:
        msgs = email_messages(result, client_name)
        if msgs:
            raw = llm.generate(msgs, schema=SCHEMA_EMAIL)
            if raw:
                allowed = build_allowlist(result)
                ok, violations = is_grounded(raw, allowed)
                if ok:
                    try:
                        parsed = json.loads(raw)
                        cache_put(key, raw)
                        return parsed
                    except Exception:
                        pass

    # Fallback — always works, pre-verified
    return email_fallback(result, client_name)


def _render_email_panel(email_data: dict, client_name: str) -> None:
    """Render email + WhatsApp side by side with send actions."""

    subject = email_data.get("subject", "")
    body    = email_data.get("body", "")
    wa      = email_data.get("whatsapp", "")

    st.markdown(f"**Subject:** {subject}")

    col1, col2 = st.columns([3, 2])

    with col1:
        st.markdown("**📧 Email**")
        st.text_area(
            "Email body",
            value=body,
            height=220,
            key=f"body_text_{client_name}",
            label_visibility="collapsed",
        )

        # mailto: deep link — opens default email client, works offline
        subject_enc = urllib.parse.quote(subject)
        body_enc    = urllib.parse.quote(body)
        mailto_href = f"mailto:?subject={subject_enc}&body={body_enc}"
        st.markdown(
            f'<a href="{mailto_href}" target="_blank">'
            f'<button style="background:#1a73e8;color:white;border:none;'
            f'padding:6px 16px;border-radius:4px;cursor:pointer;font-size:13px;">'
            f'✉️ Open in Email App</button></a>',
            unsafe_allow_html=True,
        )

    with col2:
        st.markdown("**📱 WhatsApp**")
        st.text_area(
            "WhatsApp message",
            value=wa,
            height=100,
            key=f"wa_text_{client_name}",
            label_visibility="collapsed",
        )
        word_count = len(wa.split())
        color = "🟢" if word_count <= 60 else "🔴"
        st.caption(f"{color} {word_count}/60 words")

        # wa.me deep link — works on phone/desktop, no API key, offline-safe
        # The phone number is intentionally left blank for the user to personalise
        wa_encoded  = urllib.parse.quote(wa)
        wa_href     = f"https://wa.me/?text={wa_encoded}"
        st.markdown(
            f'<a href="{wa_href}" target="_blank">'
            f'<button style="background:#25D366;color:white;border:none;'
            f'padding:6px 16px;border-radius:4px;cursor:pointer;font-size:13px;">'
            f'💬 Open in WhatsApp</button></a>',
            unsafe_allow_html=True,
        )
        st.caption(
            "Opens WhatsApp with message pre-filled. "
            "Add the client's number on your phone."
        )

    st.divider()

    # ── Copy-friendly raw text ────────────────────────────────
    with st.expander("📋 Copy raw text"):
        st.code(body, language=None)
        st.code(wa, language=None)

    # Grounding attestation
    st.caption(
        "✅ All amounts verified against engine outputs. "
        "Edit before sending if needed."
    )



def render(
    result: AnalysisResult,
    llm: OllamaBackend,
    narr: dict,
    healthy: bool,
) -> None:
    """
    Render the invoices tab.

    narr: shared narratives dict from session state.
          Keys: f'email_{client_name}' → email dict
    healthy: whether Ollama is reachable.
    """

    anomalies = result.anomalies.anomalies

    if not anomalies:
        st.info("No open invoices to display.")
        return

    st.markdown("### Open Invoice Status")
    st.caption(
        "Anomaly detection uses z-score against each client's "
        "payment history. † = still unpaid, z understates true delay."
    )

    for anom in anomalies:
        _render_invoice_row(result, llm, narr, healthy, anom)


# ── Private helpers ───────────────────────────────────────────────

def _render_invoice_row(result, llm, narr, healthy, anom) -> None:
    """Render one invoice row + optional email panel."""

    severity = anom.severity
    client   = anom.client

    # ── Severity row ──────────────────────────────────────────
    st.markdown(
        f'<div class="severity-row severity-{severity}">',
        unsafe_allow_html=True,
    )

    col1, col2, col3 = st.columns([4, 2, 1])

    with col1:
        icon = {"ANOMALY": "🔴", "WATCH": "🟡", "NORMAL": "🟢"}[severity]
        st.markdown(f"**{icon} {client}**")

        parts = [f"{anom.days_since_issue}d since issue"]
        if anom.days_overdue > 0:
            parts.append(f"{anom.days_overdue}d overdue")
        if anom.censored:
            parts.append("† t understates (still unpaid)")
        st.caption(" · ".join(parts))

    with col2:
        st.markdown(f"**{format_inr(anom.invoice_amount)}**")
        if anom.t_score > 0 and anom.std_days > 0:
            st.caption(
                f"t={anom.t_score:.1f} · "
                f"avg {anom.mean_days:.0f}d"
            )

    with col3:
        st.markdown(f"**{severity}**")

    st.markdown("</div>", unsafe_allow_html=True)

    # ── Email panel (ANOMALY only) ────────────────────────────
    if severity == "ANOMALY":
        email_key = f"email_{client}"
        email_data = narr.get(email_key)

        btn_label = (
            "✉️ Regenerate email"
            if email_data
            else "✉️ Draft collection email"
        )

        if st.button(
            btn_label,
            key=f"btn_{email_key}",
            type="primary" if not email_data else "secondary",
        ):
            email_data = _generate_email(result, llm, healthy, client)
            narr[email_key] = email_data
            st.session_state.narratives = narr
            st.rerun()

        if email_data:
            _render_email_panel(email_data, client)


def _generate_email(
    result: AnalysisResult,
    llm: OllamaBackend,
    healthy: bool,
    client_name: str,
) -> dict:
    """
    Generate or retrieve cached collection email.
    Always returns a valid dict — fallback if anything fails.
    """
    key = cache_key(result.snapshot_hash, f"email_{client_name}")

    # Cache check
    cached = cache_get(key)
    if cached:
        try:
            return json.loads(cached)
        except Exception:
            pass

    # Live generation
    if healthy:
        msgs = email_messages(result, client_name)
        if msgs:
            raw = llm.generate(msgs, schema=SCHEMA_EMAIL)
            if raw:
                allowed = build_allowlist(result)
                ok, violations = is_grounded(raw, allowed)
                if ok:
                    try:
                        parsed = json.loads(raw)
                        cache_put(key, raw)
                        return parsed
                    except Exception:
                        pass

    # Fallback — always works, pre-verified
    return email_fallback(result, client_name)


def _render_email_panel(email_data: dict, client_name: str) -> None:
    """Render the email + WhatsApp side by side."""

    subject = email_data.get("subject", "")
    body    = email_data.get("body", "")
    wa      = email_data.get("whatsapp", "")

    st.markdown(f"**Subject:** {subject}")

    col1, col2 = st.columns([3, 2])

    with col1:
        st.text_area(
            "📧 Email body",
            value=body,
            height=220,
            key=f"body_text_{client_name}",
        )

    with col2:
        st.text_area(
            "📱 WhatsApp",
            value=wa,
            height=100,
            key=f"wa_text_{client_name}",
        )
        word_count = len(wa.split())
        color = "🟢" if word_count <= 60 else "🔴"
        st.caption(f"{color} {word_count} words")

    # Copy hint
    st.caption(
        "✅ All amounts verified against engine outputs. "
        "Edit before sending if needed."
    )

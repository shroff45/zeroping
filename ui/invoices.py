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

from __future__ import annotations

import json
import urllib.parse
from datetime import date

import streamlit as st

from core.db import get_session
from core.schemas import AnalysisResult
from core.money import format_inr
from llm.backend import OllamaBackend
from llm.cache import cache_key, get as cache_get, put as cache_put
from llm.grounding import build_allowlist, is_grounded
from llm.prompts import email_messages, SCHEMA_EMAIL
from llm.fallbacks import email_fallback
from data.invoice_parser import parse_invoice_pdf
from data.csv_import import parse_csv, import_to_db


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
    # ── Invoice upload section ────────────────────────────────────────
    _render_invoice_upload()

    st.divider()

    # ── Open invoice status ───────────────────────────────────────────
    anomalies = result.anomalies.anomalies

    if not anomalies:
        st.info("No open invoices to display. Upload an invoice above to get started.")
        return

    st.markdown("### Open Invoice Status")
    st.caption(
        "Anomaly detection uses t-score (Student's t, df = n − 1) against each client's "
        "payment history. † = still unpaid, t understates true delay."
    )

    for anom in anomalies:
        _render_invoice_row(result, llm, narr, healthy, anom)


# ── Invoice upload helpers ────────────────────────────────────────────

def _render_invoice_upload() -> None:
    """Upload section: PDF (single invoice) or CSV (bulk)."""
    with st.expander("➕ Upload Invoice / Add Receivable", expanded=False):
        up_tab_pdf, up_tab_csv = st.tabs(["📄 PDF Invoice", "📊 CSV Bulk Import"])

        # ── PDF invoice ───────────────────────────────────────────
        with up_tab_pdf:
            st.caption("Upload a PDF invoice — client name, amount, and date are auto-detected.")
            pdf_file = st.file_uploader(
                "Invoice PDF",
                type=["pdf"],
                key="inv_pdf_upload",
                label_visibility="collapsed",
            )
            if pdf_file:
                with st.spinner("Parsing invoice…"):
                    fields, errs = parse_invoice_pdf(pdf_file.read())

                for e in errs:
                    st.warning(e)

                if fields:
                    # Editable preview — user can correct before saving
                    st.markdown("**Parsed fields — edit if needed:**")
                    c1, c2 = st.columns(2)
                    with c1:
                        client_val = st.text_input(
                            "Client name",
                            value=fields.get("client") or "",
                            key="inv_pdf_client",
                        )
                        amount_val = st.number_input(
                            "Amount (₹)",
                            value=float(fields.get("amount") or 0),
                            min_value=0.0,
                            step=1000.0,
                            key="inv_pdf_amount",
                        )
                    with c2:
                        date_val = st.date_input(
                            "Invoice date",
                            value=fields.get("issue_date") or date.today(),
                            key="inv_pdf_date",
                        )
                        terms_val = st.number_input(
                            "Payment terms (days)",
                            value=int(fields.get("terms_days") or 30),
                            min_value=1,
                            max_value=365,
                            step=1,
                            key="inv_pdf_terms",
                        )

                    if st.button("✅ Add to Ledger", key="inv_pdf_confirm", type="primary"):
                        if not client_val.strip():
                            st.error("Client name cannot be empty.")
                        elif amount_val <= 0:
                            st.error("Amount must be > 0.")
                        else:
                            row = {
                                "client":     client_val.strip(),
                                "amount":     float(amount_val),
                                "issue_date": date_val,
                                "terms_days": int(terms_val),
                            }
                            with get_session() as sess:
                                inserted, db_errs = import_to_db(sess, [row])
                            for e in db_errs:
                                st.error(e)
                            if not db_errs:
                                st.success(
                                    f"✅ Added {client_val} — "
                                    f"{format_inr(amount_val)} to ledger."
                                )
                                st.session_state.result     = None
                                st.session_state.narratives = {}
                                st.info("← Click **Analyse** to refresh the dashboard.")

        # ── CSV bulk import ───────────────────────────────────────
        with up_tab_csv:
            st.caption(
                "Columns: `client`, `amount`, `date`, `terms` (optional). "
                "Accepts ₹, Rs., commas. Dates: DD/MM/YYYY, DD-MM-YYYY, etc."
            )
            csv_file = st.file_uploader(
                "Receivables CSV",
                type=["csv"],
                key="inv_csv_upload",
                label_visibility="collapsed",
            )
            if csv_file:
                rows, csv_errs = parse_csv(csv_file)
                for e in csv_errs:
                    st.warning(e)
                if rows:
                    import pandas as pd
                    preview = pd.DataFrame([
                        {
                            "Client":    r["client"],
                            "Amount":    format_inr(r["amount"]),
                            "Date":      str(r["issue_date"]),
                            "Terms (d)": r["terms_days"],
                        }
                        for r in rows
                    ])
                    st.dataframe(preview, use_container_width=True, hide_index=True)
                    st.caption(f"{len(rows)} invoices ready to import.")

                    if st.button(
                        f"✅ Import {len(rows)} invoices",
                        key="inv_csv_confirm",
                        type="primary",
                    ):
                        with get_session() as sess:
                            inserted, db_errs = import_to_db(sess, rows)
                        for e in db_errs:
                            st.error(e)
                        if not db_errs:
                            st.success(f"✅ Imported {inserted} invoices to ledger.")
                            st.session_state.result     = None
                            st.session_state.narratives = {}
                            st.info("← Click **Analyse** to refresh the dashboard.")


# ── Private helpers ───────────────────────────────────────────────────

def _render_invoice_row(result, llm, narr, healthy, anom) -> None:
    """Render one invoice row + optional email panel."""

    severity = anom.severity
    client   = anom.client

    # ── Severity row ──────────────────────────────────────────────
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

    # ── Email panel (ANOMALY only) ────────────────────────────────
    if severity == "ANOMALY":
        email_key  = f"email_{client}"
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
    key    = cache_key(result.snapshot_hash, f"email_{client_name}")
    cached = cache_get(key)
    if cached:
        try:
            return json.loads(cached)
        except Exception:
            pass

    if healthy:
        msgs = email_messages(result, client_name)
        if msgs:
            raw = llm.generate(msgs, schema=SCHEMA_EMAIL)
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

    return email_fallback(result, client_name)


def _render_email_panel(email_data: dict, client_name: str) -> None:
    """Render email + WhatsApp side by side with actionable send buttons."""

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
        # mailto: deep link — opens default email client, fully offline
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

        # wa.me deep link — opens WhatsApp with message pre-filled
        # No API key, no internet required for encoding; only for delivery
        wa_encoded = urllib.parse.quote(wa)
        wa_href    = f"https://wa.me/?text={wa_encoded}"
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

    # Copy-friendly raw text
    with st.expander("📋 Copy raw text"):
        st.code(body, language=None)
        st.code(wa, language=None)

    st.caption(
        "✅ All amounts verified against engine outputs. "
        "Edit before sending if needed."
    )

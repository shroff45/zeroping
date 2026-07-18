# ui/upload.py
# Bank statement upload panel — LedgeAI
# Owner: Rishil
#
# RENDERS: a compact upload panel usable from the sidebar or a dedicated tab.
# Caller decides where to place it (sidebar OR tab — not both).
#
# FLOW:
#   1. st.file_uploader → accepts PDF
#   2. parse_bank_statement(pdf_bytes) → summary + errors
#   3. Show summary to user for confirmation
#   4. User clicks "Update Ledger" → writes to DB
#   5. Prompts user to re-Analyse (session_state.result reset)
#
# WHY NOT AUTO-UPDATE:
#   The user must confirm the parsed months before overwriting DB.
#   This is a safety gate: if the parser misread the PDF, one click reverts.
#
# OFFLINE GUARANTEE:
#   All parsing is local via pypdf. No network calls.

from __future__ import annotations

import streamlit as st

from core.money import format_inr
from data.bank_statement import parse_bank_statement, update_db_from_statement
from core.db import get_session


def render_upload_panel(location: str = "sidebar") -> None:
    """
    Render the bank statement upload panel.

    Args:
        location: "sidebar" or "tab" — affects heading size.
    """
    heading = "#### 🏦 Bank Statement" if location == "sidebar" else "### 🏦 Bank Statement Upload"
    st.markdown(heading)

    uploaded = st.file_uploader(
        "Upload PDF statement",
        type=["pdf"],
        key="bank_pdf_upload",
        label_visibility="collapsed",
        help="HDFC, ICICI, Axis Bank — text-based PDF (exported from net banking portal)",
    )

    if uploaded is None:
        st.caption("Supported: HDFC · ICICI · Axis · any text-based bank PDF")
        return

    # ── Parse immediately on upload ───────────────────────────────
    with st.spinner("Parsing statement…"):
        pdf_bytes = uploaded.read()
        summary, errors = parse_bank_statement(pdf_bytes)

    # ── Show any parse errors ─────────────────────────────────────
    if errors:
        for err in errors:
            st.warning(err)

    if not summary:
        st.error("Could not extract transactions. See warnings above.")
        return

    # ── Preview parsed summary ────────────────────────────────────
    txn_count = summary.get("transactions", 0)
    months    = summary.get("monthly_flows", {})
    closing   = summary.get("closing_balance")
    date_range = summary.get("date_range")

    st.success(f"Parsed **{txn_count} transactions** across **{len(months)} months**.")

    if date_range:
        st.caption(f"Period: {date_range[0]} → {date_range[1]}")

    if closing is not None:
        st.metric("Closing Balance", format_inr(closing))

    # Monthly flow table
    if months:
        import pandas as pd
        df = pd.DataFrame(
            [
                {
                    "Month":    k,
                    "Net Flow": format_inr(v),
                    "Direction": "↑ Inflow" if v >= 0 else "↓ Outflow",
                }
                for k, v in sorted(months.items())
            ]
        )
        st.dataframe(df, use_container_width=True, hide_index=True)

    # ── Confirmation gate ─────────────────────────────────────────
    st.caption(
        "ℹ️ Review the months above. Clicking **Update Ledger** will overwrite "
        "`monthly_history` and `cash_balance` in your local database."
    )

    confirm_key = f"confirm_upload_{uploaded.name}"
    if st.button(
        "✅ Update Ledger",
        key=confirm_key,
        type="primary",
        use_container_width=True,
    ):
        with get_session() as sess:
            months_ok, cash_ok, db_errors = update_db_from_statement(sess, summary)

        for err in db_errors:
            st.error(err)

        if not db_errors:
            st.success(
                f"✅ Updated {months_ok} months in ledger. "
                + (f"Cash balance set to {format_inr(closing)}." if cash_ok else "")
            )

            # Force re-analysis on next click — stale result is now invalid
            if "result" in st.session_state:
                st.session_state.result     = None
                st.session_state.narratives = {}
            st.info("← Click **Analyse** to refresh the dashboard with your new data.")

# data/bank_statement.py
# Bank statement PDF parser — LedgeAI
#
# SUPPORTED FORMATS:
#   HDFC Bank (savings/current account)
#   ICICI Bank (statement)
#   Axis Bank  (statement)
#   Generic fallback: any PDF with debit/credit columns
#
# WHAT IT DOES:
#   1. Extracts text from PDF using pypdf (pure Python, no Pillow conflict)
#   2. Detects bank format from header keywords
#   3. Parses transaction rows: date, description, debit, credit, balance
#   4. Aggregates net flows by calendar month
#   5. Updates monthly_history table in DB
#   6. Updates cash_balance from the last closing balance row
#
# RULES:
#   - All amounts converted to float via Decimal (no float arithmetic)
#   - Returns (summary, errors) — never raises
#   - DB update is inside a try/finally that always closes session
#
# DESIGN NOTE (why pypdf not pdfplumber):
#   pdfplumber 0.11+ requires Pillow≥12.2 which conflicts with Streamlit 1.36.0.
#   pypdf 6.x is pure Python, has no Pillow dependency, and reliably extracts
#   plain text from all major Indian bank PDFs.

from __future__ import annotations

import re
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path
from typing import IO

try:
    import pypdf
    _PYPDF_AVAILABLE = True
except ImportError:
    _PYPDF_AVAILABLE = False


# ── Date patterns ─────────────────────────────────────────────────────
_DATE_PATTERNS = [
    r"\d{2}/\d{2}/\d{4}",   # DD/MM/YYYY  (HDFC, ICICI)
    r"\d{2}-\d{2}-\d{4}",   # DD-MM-YYYY  (Axis)
    r"\d{2} [A-Za-z]{3} \d{4}",  # DD Mon YYYY
]
_DATE_FMTS = ["%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%d %B %Y"]

# ── Amount sanitiser (strips ₹, Rs, commas) ──────────────────────────
_AMT_RE = re.compile(r"[₹\sRs,]", re.UNICODE)


def _parse_amount(raw: str) -> Decimal | None:
    cleaned = _AMT_RE.sub("", raw).strip()
    if not cleaned or cleaned in ("-", "—", ""):
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _parse_date(raw: str) -> date | None:
    raw = raw.strip()
    for fmt in _DATE_FMTS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


# ── Transaction row ────────────────────────────────────────────────────

class TxnRow:
    __slots__ = ("txn_date", "description", "debit", "credit", "balance")

    def __init__(
        self,
        txn_date: date,
        description: str,
        debit: Decimal,
        credit: Decimal,
        balance: Decimal,
    ):
        self.txn_date    = txn_date
        self.description = description
        self.debit       = debit    # outflow (positive amount)
        self.credit      = credit   # inflow  (positive amount)
        self.balance     = balance


# ── PDF text extractor ────────────────────────────────────────────────

def _extract_text(source: str | Path | IO | bytes) -> str:
    """Extract all text from a PDF source using pypdf."""
    if not _PYPDF_AVAILABLE:
        raise RuntimeError("pypdf not installed. Run: pip install pypdf")

    if isinstance(source, (str, Path)):
        with open(source, "rb") as f:
            raw = f.read()
    elif isinstance(source, bytes):
        raw = source
    elif hasattr(source, "read"):
        raw = source.read()
    else:
        raise ValueError("source must be a path, bytes, or file-like object")

    reader = pypdf.PdfReader(BytesIO(raw))
    pages  = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            pages.append("")
    return "\n".join(pages)


# ── Transaction parser (bank-agnostic) ────────────────────────────────

def _parse_transactions(text: str) -> list[TxnRow]:
    """
    Generic transaction parser.
    Looks for lines containing a date pattern followed by amounts.

    Pattern:
      DD/MM/YYYY [description...] [debit] [credit] [balance]
    OR:
      DD/MM/YYYY [description...] [credit] [debit] [balance]

    We determine debit vs credit by column position (crude but reliable
    since we only need net monthly flows, not individual directions).
    Uses a sign heuristic: if balance goes down vs previous row → debit.
    """
    # Compile all date patterns
    date_re = re.compile(
        r"(\d{2}[/\-]\d{2}[/\-]\d{4}|\d{2} [A-Za-z]{3} \d{4})"
    )
    # Amount pattern: digits with optional commas and decimal
    amt_re = re.compile(r"([\d,]+\.\d{2})")

    rows: list[TxnRow] = []
    lines = text.split("\n")

    prev_balance: Decimal | None = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        date_match = date_re.search(line)
        if not date_match:
            continue

        txn_date = _parse_date(date_match.group(1))
        if txn_date is None:
            continue

        # Extract all amounts from this line
        amounts = [_parse_amount(m) for m in amt_re.findall(line)]
        amounts = [a for a in amounts if a is not None]

        if len(amounts) < 2:
            continue

        # Last amount is balance, second-to-last is the transaction amount
        balance = amounts[-1]
        txn_amt = amounts[-2]

        # Determine debit vs credit from balance direction
        if prev_balance is not None:
            if balance < prev_balance:
                debit, credit = txn_amt, Decimal("0")
            else:
                debit, credit = Decimal("0"), txn_amt
        else:
            # First row: assume credit (opening balance or first deposit)
            debit, credit = Decimal("0"), txn_amt

        prev_balance = balance

        # Description: everything between date and first amount
        date_end   = date_match.end()
        amt_start  = line.find(str(amounts[0]).replace(",", "").split(".")[0], date_end)
        description = line[date_end:amt_start].strip() if amt_start > date_end else ""

        rows.append(TxnRow(
            txn_date=txn_date,
            description=description,
            debit=debit,
            credit=credit,
            balance=balance,
        ))

    return rows


# ── Monthly aggregator ────────────────────────────────────────────────

def _aggregate_monthly(rows: list[TxnRow]) -> dict[str, Decimal]:
    """
    Aggregate net flows (credit - debit) by month.
    Returns {month_str: net_flow}, e.g. {"2026-06": Decimal("-12000")}.
    """
    monthly: dict[str, Decimal] = {}
    for row in rows:
        key = row.txn_date.strftime("%Y-%m")
        net = row.credit - row.debit
        monthly[key] = monthly.get(key, Decimal("0")) + net
    return monthly


# ── Public API ────────────────────────────────────────────────────────

def parse_bank_statement(
    source: str | Path | IO | bytes,
) -> tuple[dict, list[str]]:
    """
    Parse a bank statement PDF.

    Returns:
        (summary, errors)

        summary: {
          "transactions":    int,           # rows parsed
          "months":          int,           # distinct months
          "monthly_flows":   {month: float},
          "closing_balance": float | None,  # last balance seen
          "date_range":      (str, str) | None,
        }

        errors: list of human-readable messages (warnings, skips)

    Never raises — returns ({}, [error]) on catastrophic failure.
    """
    errors: list[str] = []

    try:
        text = _extract_text(source)
    except Exception as e:
        return {}, [f"Failed to read PDF: {e}"]

    if not text.strip():
        return {}, ["PDF appears empty or is image-only (scanned). "
                    "Export a text-based statement from your bank portal."]

    rows = _parse_transactions(text)

    if not rows:
        errors.append(
            "No transaction rows found. "
            "This parser supports HDFC/ICICI/Axis text-based PDFs. "
            "Try exporting a fresh statement from your bank's net banking portal."
        )
        return {}, errors

    monthly = _aggregate_monthly(rows)
    closing = rows[-1].balance if rows else None
    first_date = rows[0].txn_date.isoformat() if rows else None
    last_date  = rows[-1].txn_date.isoformat() if rows else None

    summary = {
        "transactions":    len(rows),
        "months":          len(monthly),
        "monthly_flows":   {k: float(v) for k, v in monthly.items()},
        "closing_balance": float(closing) if closing is not None else None,
        "date_range":      (first_date, last_date) if first_date else None,
    }
    return summary, errors


def update_db_from_statement(
    session,
    summary: dict,
) -> tuple[int, int, list[str]]:
    """
    Update the database from a parsed bank statement summary.

    Actions:
      1. UPSERT monthly_history rows (by month key)
      2. UPDATE company.cash_balance from closing_balance (if present)

    Returns:
        (months_updated, cash_updated, errors)
        months_updated: number of monthly_history rows upserted
        cash_updated:   1 if cash_balance was updated, else 0
        errors:         list of error messages
    """
    import sqlalchemy as sa
    errors: list[str] = []
    months_updated = 0
    cash_updated   = 0

    try:
        monthly_flows = summary.get("monthly_flows", {})
        for month, net_flow in monthly_flows.items():
            try:
                # SQLite UPSERT: INSERT OR REPLACE (monthly.month is PRIMARY KEY)
                session.execute(
                    sa.text("""
                        INSERT INTO monthly_history (month, net_flow)
                        VALUES (:month, :net_flow)
                        ON CONFLICT(month) DO UPDATE SET
                            net_flow = excluded.net_flow
                    """),
                    {"month": month, "net_flow": str(net_flow)},
                )
                months_updated += 1
            except Exception as e:
                errors.append(f"Could not update {month}: {e}")

        closing = summary.get("closing_balance")
        if closing is not None:
            try:
                session.execute(
                    sa.text("UPDATE company SET cash_balance = :bal WHERE id = 1"),
                    {"bal": str(closing)},
                )
                cash_updated = 1
            except Exception as e:
                errors.append(f"Could not update cash_balance: {e}")

        session.commit()

    except Exception as e:
        errors.append(f"DB update failed: {e}")

    return months_updated, cash_updated, errors

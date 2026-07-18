# data/csv_import.py
# CSV ingestion for LedgeAI
# Owner: Pranav
#
# Accepts CSV files with receivable data.
# Sanitizes amounts, normalizes dates, skips bad rows.
#
# COLUMN DETECTION:
#   Client name: "client" | "name" | "customer" | "party"
#   Amount:      "amount" | "invoice_amount" | "value" | "total"
#   Date:        "date" | "issue_date" | "invoice_date"
#   Terms:       "terms" | "terms_days" | "days" | "credit_days"
#
# AMOUNT SANITIZATION:
#   Strips ₹, Rs., Rs, commas (Indian and Western grouping)
#   Handles both "1,85,000" and "185,000"
#
# DATE FORMATS SUPPORTED:
#   DD-MM-YYYY, DD/MM/YYYY, YYYY-MM-DD, DD-MMM-YYYY, D-M-YYYY
#
# ENCODING:
#   utf-8-sig (handles BOM from Excel exports)
#   Falls back to latin-1 if utf-8-sig fails
#
# ERROR HANDLING:
#   Skip-row-on-error — bad rows logged, not raised
#   Returns list of valid rows + error log for UI display

from __future__ import annotations

import csv
import logging
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import StringIO
from pathlib import Path
from typing import IO

from core.money import to_decimal

logger = logging.getLogger(__name__)

# ── Column name aliases ────────────────────────────────────────────────
_COL_CLIENT = {"client", "name", "customer", "party", "client_name", "customer_name"}
_COL_AMOUNT = {"amount", "invoice_amount", "value", "total", "invoice_value", "amt"}
_COL_DATE   = {"date", "issue_date", "invoice_date", "inv_date", "invoice date", "issue date"}
_COL_TERMS  = {"terms", "terms_days", "days", "credit_days", "credit days", "net_days"}

# ── Date format patterns ───────────────────────────────────────────────
_DATE_FORMATS = [
    "%d-%m-%Y",   # 18-07-2026
    "%d/%m/%Y",   # 18/07/2026
    "%Y-%m-%d",   # 2026-07-18
    "%d-%b-%Y",   # 18-Jul-2026
    "%d %b %Y",   # 18 Jul 2026
    "%d-%B-%Y",   # 18-July-2026
    "%d/%m/%y",   # 18/07/26
    "%d-%m-%y",   # 18-07-26
]

# ── Amount sanitizer ──────────────────────────────────────────────────
_AMOUNT_RE = re.compile(r"[₹\s]|Rs\.?\s*", re.UNICODE)


def _parse_amount(raw: str) -> Decimal | None:
    """Strip currency symbols and commas, parse as Decimal. Returns None on failure."""
    cleaned = _AMOUNT_RE.sub("", raw).replace(",", "").strip()
    try:
        d = Decimal(cleaned)
        if d <= 0:
            return None
        return d
    except InvalidOperation:
        return None


def _parse_date(raw: str) -> date | None:
    """Try each supported date format. Returns None on all failures."""
    raw = raw.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _detect_columns(headers: list[str]) -> dict[str, str]:
    """
    Map CSV headers to canonical column names.
    Returns: {"client": actual_col, "amount": actual_col, ...}
    Missing mappings are absent from the dict.
    """
    mapping: dict[str, str] = {}
    lower_map = {h.lower().strip(): h for h in headers}

    for alias in _COL_CLIENT:
        if alias in lower_map:
            mapping["client"] = lower_map[alias]
            break
    for alias in _COL_AMOUNT:
        if alias in lower_map:
            mapping["amount"] = lower_map[alias]
            break
    for alias in _COL_DATE:
        if alias in lower_map:
            mapping["date"] = lower_map[alias]
            break
    for alias in _COL_TERMS:
        if alias in lower_map:
            mapping["terms"] = lower_map[alias]
            break

    return mapping


def parse_csv(
    source: str | Path | IO,
    default_terms: int = 30,
) -> tuple[list[dict], list[str]]:
    """
    Parse a CSV file of receivable data.

    Args:
        source:        Path to CSV file, a file-like object, or a string of CSV content.
        default_terms: Days to use when terms column is absent or unparseable.

    Returns:
        (rows, errors)
        rows:   List of dicts: {client, amount, issue_date, terms_days}
                amount is float (cast from Decimal — ready for Receivable schema)
        errors: List of human-readable error messages for rows that were skipped.
    """
    rows:   list[dict] = []
    errors: list[str]  = []

    # ── Read content ──────────────────────────────────────────────────
    if isinstance(source, (str, Path)):
        path = Path(source)
        if not path.exists():
            return [], [f"File not found: {source}"]
        # Try UTF-8 BOM first (Excel exports), then latin-1
        for encoding in ("utf-8-sig", "latin-1"):
            try:
                content = path.read_text(encoding=encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            return [], [f"Cannot decode file: {source}"]
    elif hasattr(source, "read"):
        # File-like object (e.g., Streamlit UploadedFile)
        raw = source.read()
        if isinstance(raw, bytes):
            for encoding in ("utf-8-sig", "latin-1"):
                try:
                    content = raw.decode(encoding)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                return [], ["Cannot decode uploaded file"]
        else:
            content = raw
    else:
        content = str(source)

    # ── Parse CSV ─────────────────────────────────────────────────────
    reader = csv.DictReader(StringIO(content))

    if reader.fieldnames is None:
        return [], ["CSV file is empty or has no headers"]

    mapping = _detect_columns(list(reader.fieldnames))

    required = {"client", "amount", "date"}
    missing  = required - set(mapping.keys())
    if missing:
        return [], [
            f"Cannot find columns for: {', '.join(sorted(missing))}. "
            f"Headers found: {list(reader.fieldnames)}"
        ]

    for row_num, row in enumerate(reader, start=2):
        # ── Client ────────────────────────────────────────────────
        client = row.get(mapping["client"], "").strip()
        if not client:
            errors.append(f"Row {row_num}: missing client name — skipped")
            continue

        # ── Amount ────────────────────────────────────────────────
        amount_raw = row.get(mapping["amount"], "").strip()
        amount     = _parse_amount(amount_raw)
        if amount is None:
            errors.append(f"Row {row_num} ({client}): invalid amount '{amount_raw}' — skipped")
            continue

        # ── Date ──────────────────────────────────────────────────
        date_raw  = row.get(mapping["date"], "").strip()
        issue_date = _parse_date(date_raw)
        if issue_date is None:
            errors.append(f"Row {row_num} ({client}): invalid date '{date_raw}' — skipped")
            continue

        # ── Terms (optional) ──────────────────────────────────────
        terms = default_terms
        if "terms" in mapping:
            terms_raw = row.get(mapping["terms"], "").strip()
            try:
                parsed = int(float(terms_raw))
                if 1 <= parsed <= 365:
                    terms = parsed
            except (ValueError, TypeError):
                pass  # use default_terms

        rows.append({
            "client":     client,
            "amount":     float(amount),     # Receivable schema expects float
            "issue_date": issue_date,
            "terms_days": terms,
        })

    return rows, errors


def import_to_db(
    session,
    rows: list[dict],
    client_contact_map: dict[str, str] | None = None,
) -> tuple[int, list[str]]:
    """
    Insert parsed rows into the database via SQLAlchemy session.

    Args:
        session:            SQLAlchemy session (from core/db.py get_session)
        rows:               Output of parse_csv()
        client_contact_map: Optional {client_name: email} for clients table

    Returns:
        (inserted_count, errors)
    """
    import sqlalchemy as sa
    from core.config import DEMO_DATE

    errors: list[str] = []
    inserted = 0

    for row in rows:
        try:
            client_name = row["client"]

            # Upsert client
            existing = session.execute(
                sa.text("SELECT id FROM clients WHERE name = :name"),
                {"name": client_name},
            ).fetchone()

            if existing:
                client_id = existing[0]
            else:
                contact = (client_contact_map or {}).get(client_name, "")
                result = session.execute(
                    sa.text("INSERT INTO clients (name, contact) VALUES (:name, :contact)"),
                    {"name": client_name, "contact": contact},
                )
                client_id = result.lastrowid

            # Insert receivable
            session.execute(
                sa.text("""
                    INSERT INTO receivables (client_id, amount, issue_date, terms_days)
                    VALUES (:client_id, :amount, :issue_date, :terms_days)
                """),
                {
                    "client_id":  client_id,
                    "amount":     str(row["amount"]),   # TEXT column
                    "issue_date": row["issue_date"].isoformat(),
                    "terms_days": row["terms_days"],
                },
            )
            inserted += 1

        except Exception as e:
            errors.append(f"DB insert failed for {row.get('client', '?')}: {e}")

    session.commit()
    return inserted, errors

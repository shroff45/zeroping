# data/invoice_parser.py
# Invoice PDF parser — LedgeAI
#
# Parses individual invoice PDFs to extract:
#   client_name, amount, issue_date, terms_days
#
# SUPPORTED FORMATS:
#   Any text-based PDF invoice (Zoho, QuickBooks, Tally, custom templates)
#   Key field detection via keyword heuristics (not layout-sensitive)
#
# FIELD EXTRACTION RULES:
#   client:    Line after "Bill To:" / "Client:" / "To:" / "Customer:"
#   amount:    Last ₹/Rs amount on page (usually "Total" or "Grand Total")
#   date:      Line containing "Invoice Date:" / "Date:" / "Issue Date:"
#   terms:     Line containing "Due:" / "Terms:" / "Net " / "Payment Terms"
#
# USES: pypdf (pure Python, no Pillow dependency — safe with Streamlit 1.36)
#
# RETURNS: (fields_dict, errors_list)
#   fields_dict keys: client, amount, issue_date, terms_days
#   All values are Python native types (str/float/date/int)

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path
from typing import IO

try:
    import pypdf
    _PYPDF_OK = True
except ImportError:
    _PYPDF_OK = False

# ── Amount patterns ───────────────────────────────────────────────────
_AMT_STRIP = re.compile(r"[₹\s,]|Rs\.?\s*", re.UNICODE)
_AMT_FIND  = re.compile(
    r"(?:₹|Rs\.?\s*|INR\s*)([\d,]+(?:\.\d{2})?)"
    r"|(?:Total|Grand Total|Amount Due|Balance Due)[^\d]*([\d,]+(?:\.\d{2})?)",
    re.IGNORECASE,
)

# ── Date formats ──────────────────────────────────────────────────────
_DATE_FMTS = [
    "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d",
    "%d %b %Y", "%d-%b-%Y", "%d %B %Y",
    "%B %d, %Y", "%b %d, %Y",
    "%d/%m/%y", "%d-%m-%y",
]

# ── Keyword triggers ──────────────────────────────────────────────────
_CLIENT_KW  = re.compile(r"^(bill\s*to|client|to|customer|billed\s*to)\s*:?\s*", re.I)
_DATE_KW    = re.compile(r"(invoice\s*date|date\s*of\s*issue|issue\s*date|date)\s*:?\s*", re.I)
_TERMS_KW   = re.compile(r"(payment\s*terms?|due\s*date|net\s*\d+|terms?)\s*:?\s*", re.I)
_DUE_DAYS   = re.compile(r"net\s*(\d+)", re.I)


def _extract_text(source) -> str:
    if not _PYPDF_OK:
        raise RuntimeError("pypdf not installed")
    if isinstance(source, (str, Path)):
        raw = Path(source).read_bytes()
    elif isinstance(source, bytes):
        raw = source
    elif hasattr(source, "read"):
        raw = source.read()
    else:
        raise ValueError("source must be path, bytes, or file-like")
    reader = pypdf.PdfReader(BytesIO(raw))
    return "\n".join(
        page.extract_text() or "" for page in reader.pages
    )


def _parse_amount(raw: str) -> float | None:
    cleaned = _AMT_STRIP.sub("", raw).strip()
    if not cleaned:
        return None
    try:
        return float(Decimal(cleaned))
    except (InvalidOperation, ValueError):
        return None


def _parse_date(raw: str) -> date | None:
    raw = raw.strip()
    for fmt in _DATE_FMTS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _extract_amount_from_text(text: str) -> float | None:
    """Find the largest ₹ amount — usually the invoice total."""
    amounts = []
    for m in _AMT_FIND.finditer(text):
        raw = m.group(1) or m.group(2)
        if raw:
            a = _parse_amount(raw.replace(",", ""))
            if a and a > 0:
                amounts.append(a)
    return max(amounts) if amounts else None


def _extract_date_from_text(text: str) -> date | None:
    """Find first date near a date-keyword line."""
    date_re = re.compile(
        r"\b(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}"
        r"|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}"
        r"|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})\b"
    )
    lines = text.split("\n")
    # Pass 1: lines with date keyword
    for line in lines:
        if _DATE_KW.search(line):
            m = date_re.search(line)
            if m:
                d = _parse_date(m.group(1))
                if d:
                    return d
    # Pass 2: first date found anywhere
    for line in lines:
        m = date_re.search(line)
        if m:
            d = _parse_date(m.group(1))
            if d:
                return d
    return None


def _extract_client_from_text(text: str) -> str | None:
    """Find client name from Bill To / To / Client: line."""
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if _CLIENT_KW.match(line.strip()):
            # Client name is the remainder of this line or the next non-empty line
            remainder = _CLIENT_KW.sub("", line.strip()).strip()
            if remainder and len(remainder) > 1:
                return remainder
            # Try next line
            for j in range(i + 1, min(i + 4, len(lines))):
                candidate = lines[j].strip()
                if candidate and not any(
                    kw in candidate.lower()
                    for kw in ("invoice", "date", "number", "amount", "total", "gstin")
                ):
                    return candidate
    return None


def _extract_terms_from_text(text: str) -> int:
    """Extract payment terms in days. Defaults to 30."""
    # "Net 30", "Net30", "30 days"
    m = _DUE_DAYS.search(text)
    if m:
        days = int(m.group(1))
        if 1 <= days <= 365:
            return days
    # "Due Date: 15/08/2026" vs issue_date — would need both; default
    return 30


def parse_invoice_pdf(
    source,
    default_terms: int = 30,
) -> tuple[dict, list[str]]:
    """
    Parse a single invoice PDF.

    Returns:
        (fields, errors)
        fields: {client, amount, issue_date, terms_days}  — None values where not found
        errors: human-readable warnings
    """
    errors: list[str] = []

    try:
        text = _extract_text(source)
    except Exception as e:
        return {}, [f"Cannot read PDF: {e}"]

    if not text.strip():
        return {}, [
            "PDF appears empty or is image-based (scanned). "
            "Export a text-based invoice from your billing software."
        ]

    client    = _extract_client_from_text(text)
    amount    = _extract_amount_from_text(text)
    issue_dt  = _extract_date_from_text(text)
    terms     = _extract_terms_from_text(text)

    if not client:
        errors.append("Could not detect client name. Check 'Bill To:' field in invoice.")
    if not amount:
        errors.append("Could not detect invoice amount. Ensure ₹/Rs total is present.")
    if not issue_dt:
        errors.append("Could not detect invoice date. Defaulting to today.")
        issue_dt = date.today()

    fields = {
        "client":     client or "",
        "amount":     amount,
        "issue_date": issue_dt,
        "terms_days": terms,
    }
    return fields, errors

# core/repository.py
# B25 — Single DB read → frozen CompanySnapshot
# Owner: Pranav
# Deps: B05, B06, B07
#
# RULE: One function. One read. Returns frozen snapshot.
# Everything downstream is a pure function of this object.
# No second DB read anywhere in the codebase.

from __future__ import annotations

from datetime import date

import sqlalchemy as sa
from sqlalchemy.orm import Session

from core.config import DEMO_DATE
from core.schemas import (
    CompanySnapshot,
    MonthlyNet,
    PaymentRecord,
    Payable,
    Receivable,
)


def load_snapshot(session: Session) -> CompanySnapshot:
    """
    Read the database exactly once.
    Return a frozen CompanySnapshot.

    Option B is enforced here:
      receivables query filters WHERE paid_date IS NULL
      The snapshot contains open invoices only.
      Engines never see paid invoices.
      Engines never reference paid_date.
    """

    # ── Cash balance ─────────────────────────────────────────────
    cash_row = session.execute(
        sa.text("SELECT cash_balance FROM company WHERE id = 1")
    ).fetchone()

    if cash_row is None:
        raise RuntimeError(
            "Company row missing. Run data/seed.py first."
        )
    cash_balance = float(cash_row[0])

    # ── Open receivables (Option B: paid_date IS NULL) ────────────
    recv_rows = session.execute(sa.text("""
        SELECT c.name, r.amount, r.issue_date, r.terms_days
        FROM   receivables r
        JOIN   clients c ON c.id = r.client_id
        WHERE  r.paid_date IS NULL
    """)).fetchall()

    receivables = tuple(
        Receivable(
            client=row[0],
            amount=float(row[1]),
            issue_date=date.fromisoformat(row[2]),
            terms_days=int(row[3]),
        )
        for row in recv_rows
    )

    # ── Payables ──────────────────────────────────────────────────
    pay_rows = session.execute(sa.text("""
        SELECT payee, amount, due_date, category, flexible
        FROM   payables
        ORDER  BY due_date ASC
    """)).fetchall()

    payables = tuple(
        Payable(
            payee=row[0],
            amount=float(row[1]),
            due_date=date.fromisoformat(row[2]),
            category=row[3],
            flexible=bool(row[4]),
        )
        for row in pay_rows
    )

    # ── Payment history ───────────────────────────────────────────
    hist_rows = session.execute(sa.text("""
        SELECT c.name, h.days_to_pay
        FROM   payment_history h
        JOIN   clients c ON c.id = h.client_id
        ORDER  BY h.id ASC
    """)).fetchall()

    payment_history = tuple(
        PaymentRecord(
            client=row[0],
            days_to_pay=int(row[1]),
        )
        for row in hist_rows
    )

    # ── Monthly history ───────────────────────────────────────────
    monthly_rows = session.execute(sa.text("""
        SELECT month, net_flow
        FROM   monthly_history
        ORDER  BY month ASC
    """)).fetchall()

    monthly_history = tuple(
        MonthlyNet(
            month=row[0],
            net_flow=float(row[1]),
        )
        for row in monthly_rows
    )

    return CompanySnapshot(
        as_of=DEMO_DATE,
        cash_balance=cash_balance,
        receivables=receivables,
        payables=payables,
        payment_history=payment_history,
        monthly_history=monthly_history,
    )

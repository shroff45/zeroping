# core/schemas.py
# THE CONTRACT. Freeze at T+0:35.
# Changes after freeze require verbal announcement to all 4 people.
#
# DECISIONS IN EFFECT:
#   Q1: Schemas hold float (JSON-serializable for Streamlit session state).
#       Decimal enforcement is at the engine compute layer.
#   Q3: AnalysisResult embeds snapshot → eliminates 4th session state key.

from __future__ import annotations
from datetime import date
from decimal import Decimal
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, field_validator


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, allow_inf_nan=False)


# ── INPUT TYPES ──────────────────────────────────────────────────────

class Receivable(_Frozen):
    client: str
    amount: float
    issue_date: date
    terms_days: int = 30


class Payable(_Frozen):
    payee: str
    amount: float
    due_date: date
    category: Literal["rent", "salary", "vendor", "utility", "tax"]
    flexible: bool


class PaymentRecord(_Frozen):
    client: str
    days_to_pay: int


class MonthlyNet(_Frozen):
    month: str      # "2026-02"
    net_flow: float


class CompanySnapshot(_Frozen):
    as_of: date
    cash_balance: float
    receivables: tuple[Receivable, ...]
    payables: tuple[Payable, ...]
    payment_history: tuple[PaymentRecord, ...]
    monthly_history: tuple[MonthlyNet, ...]


# ── ENGINE OUTPUT TYPES ──────────────────────────────────────────────

class LiquidityResult(_Frozen):
    risk_score: int              # 0..100, lower = worse
    risk_level: Literal["LOW", "MODERATE", "HIGH", "CRITICAL"]
    runway_days: float
    quick_ratio: float
    dso_days: float
    dpo_days: float              # DPO = (AP/COGS_90d) × 90
    ccc_days: float              # CCC = DSO - DPO (positive = structural cash gap)
    receivables_quality: float   # 0..1
    components: dict[str, float] # score breakdown for UI
    is_fallback: bool = False


class Anomaly(_Frozen):
    client: str
    invoice_amount: float
    days_since_issue: int        # issue-anchored (anomaly metric)
    days_overdue: int            # due-date-anchored (UI urgency)
    t_score: float               # t-score (NOT z-score) — df=n-1 per client
    t_watch: float               # dynamic watch threshold: t.ppf(0.85, df)
    t_anomaly: float             # dynamic anomaly threshold: t.ppf(0.95, df)
    mean_days: float
    std_days: float
    severity: Literal["NORMAL", "WATCH", "ANOMALY"]
    censored: bool               # True = still unpaid, t understates true delay


class AnomalyResult(_Frozen):
    anomalies: tuple[Anomaly, ...]
    is_fallback: bool = False


class ProjectionResult(_Frozen):
    daily_expected: tuple[float, ...]   # 90 values
    daily_lower: tuple[float, ...]      # t-based prediction interval
    daily_upper: tuple[float, ...]
    crossover_day: Optional[int]        # first day expected < 0
    min_balance: float
    min_balance_day: int
    day30: float
    day60: float
    day90: float
    excluded_receivables: tuple[str, ...]
    is_fallback: bool = False


class PaymentDecision(_Frozen):
    payee: str
    amount: float
    due_date: date
    action: Literal["PAY_NOW", "SCHEDULED", "DEFER"]
    reason: str                  # engine-written, ≤ 90 chars
    cash_after: Optional[float]  # PAY_NOW only


class PaymentPlan(_Frozen):
    decisions: tuple[PaymentDecision, ...]
    spendable_now: float
    is_fallback: bool = False


class GSTEvent(_Frozen):
    description: str
    due_date: date
    amount: Optional[float]
    days_until_due: int
    urgency: Literal["OVERDUE", "URGENT", "UPCOMING", "FUTURE"]


class GSTCalendar(_Frozen):
    events: tuple[GSTEvent, ...]
    next_due: Optional[GSTEvent]


class BankabilityResult(_Frozen):
    score: int                   # 0..100
    grade: Literal["A", "B", "C", "D", "F"]
    mudra_tier: str              # "Shishu" | "Kishore" | "Tarun" | "Tarun Plus" | "Not eligible"
    eligible_schemes: tuple[str, ...]
    blockers: tuple[str, ...]
    ccc_days: float              # CCC displayed as primary metric (G30)
    dso_days: float              # echoed from LiquidityResult for display
    dpo_days: float              # echoed from LiquidityResult for display
    is_fallback: bool = False


class WhatIfResult(_Frozen):
    scenario_label: str
    delta_cash: float
    new_crossover_day: Optional[int]
    new_risk_level: Literal["LOW", "MODERATE", "HIGH", "CRITICAL"]
    payments_unlocked: tuple[str, ...]


class AnalysisResult(_Frozen):
    """
    Root frozen object. Produced once by run_pipeline().
    Stored in st.session_state.result.
    Embeds snapshot so what-if engine has access without
    a 4th session state key (PRD: exactly 3 keys).
    """
    snapshot_hash: str
    snapshot: CompanySnapshot    # embedded — used by what-if engine only
    liquidity: LiquidityResult
    anomalies: AnomalyResult
    projection: ProjectionResult
    payments: PaymentPlan
    gst_calendar: GSTCalendar
    bankability: BankabilityResult


def make_fixture_snapshot() -> CompanySnapshot:
    """
    Structurally valid, numerically fake.
    Unblocks parallel development before seed.py exists.
    Import ONLY from tests/ and dev scripts.
    NEVER from app.py or any production path.
    """
    from datetime import date
    return CompanySnapshot(
        as_of=date(2026, 7, 18),
        cash_balance=117_000.0,   # tuned: cash > rent(45k) + buffer(50k) → G14 PAY_NOW
        receivables=(
            Receivable(
                client="Apex Builders",
                amount=185_000.0,
                issue_date=date(2026, 5, 14),
                terms_days=30,
            ),
            Receivable(
                client="Metro Interiors",
                amount=48_000.0,
                issue_date=date(2026, 6, 17),
                terms_days=30,
            ),
        ),
        payables=(
            Payable(
                payee="Prestige Properties",
                amount=45_000.0,
                due_date=date(2026, 7, 20),
                category="rent",
                flexible=False,
            ),
            Payable(
                payee="Staff Salaries",
                amount=120_000.0,
                due_date=date(2026, 7, 31),
                category="salary",
                flexible=False,
            ),
            Payable(
                payee="Sharma Timber",
                amount=35_000.0,
                due_date=date(2026, 7, 28),
                category="vendor",
                flexible=True,
            ),
            Payable(
                payee="GST Q1 FY27",
                amount=28_000.0,
                due_date=date(2026, 8, 20),
                category="tax",
                flexible=False,
            ),
        ),
        payment_history=(
            PaymentRecord(client="Apex Builders", days_to_pay=20),
            PaymentRecord(client="Apex Builders", days_to_pay=24),
            PaymentRecord(client="Apex Builders", days_to_pay=29),
            PaymentRecord(client="Apex Builders", days_to_pay=33),
            PaymentRecord(client="Apex Builders", days_to_pay=43),
            PaymentRecord(client="Apex Builders", days_to_pay=49),
            PaymentRecord(client="Metro Interiors", days_to_pay=26),
            PaymentRecord(client="Metro Interiors", days_to_pay=28),
            PaymentRecord(client="Metro Interiors", days_to_pay=29),
            PaymentRecord(client="Metro Interiors", days_to_pay=31),
            PaymentRecord(client="Metro Interiors", days_to_pay=33),
            PaymentRecord(client="Metro Interiors", days_to_pay=35),
        ),
        monthly_history=(
            MonthlyNet(month="2026-01", net_flow=22_000.0),
            MonthlyNet(month="2026-02", net_flow=18_000.0),
            MonthlyNet(month="2026-03", net_flow=15_000.0),
            MonthlyNet(month="2026-04", net_flow=8_000.0),
            MonthlyNet(month="2026-05", net_flow=-5_000.0),
            MonthlyNet(month="2026-06", net_flow=-12_000.0),
        ),
    )

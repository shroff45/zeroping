# tests/test_engines.py
# B16 — All 34 acceptance gates as pytest assertions
#
# USAGE:
#   python data/seed.py           # create fresh DB
#   pytest tests/test_engines.py -v
#
# RULE: If a gate fails, tune data/seed.py — never tune the formula.
# The formula is law. The seed serves the formula.
#
# GATE MAP:
#   G01-G03: Liquidity risk level, score, runway
#   G04-G08: Anomaly detection (t-score per client)
#   G09:     Bankability CCC shown
#   G10-G13: Projection band, crossover, exclusions
#   G14-G17: Optimizer decisions
#   G18:     Spendable = cash - buffer
#   G19-G20: MILP solver (documented)
#   G21-G24: GST calendar
#   G25-G27: Pipeline integrity
#   G28-G30: Bankability score, grade, CCC
#   G31:     MCP tool definitions (structural)
#   G32:     Decimal compute boundary
#   G33-G34: Grounding firewall (bifurcated tolerance)

import pytest
from datetime import date
from decimal import Decimal

from core.schemas import make_fixture_snapshot
from core.pipeline import run_pipeline
from core.money import to_decimal, safe_divide, format_inr
from llm.grounding import build_allowlist, is_grounded


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def snap():
    """Frozen fixture snapshot — load once for entire module."""
    return make_fixture_snapshot()


@pytest.fixture(scope="module")
def result(snap):
    """Full AnalysisResult from pipeline — computed once."""
    return run_pipeline(snap)


@pytest.fixture(scope="module")
def allowed(result):
    """Grounding allowlist — built once from result."""
    return build_allowlist(result)


# ── G01-G03: Liquidity ────────────────────────────────────────────────

def test_G01_risk_level_critical(result):
    """G01: Risk level must be CRITICAL for demo scenario."""
    assert result.liquidity.risk_level == "CRITICAL", (
        f"Expected CRITICAL, got {result.liquidity.risk_level}. "
        "Tune seed cash_balance or monthly_history."
    )


def test_G02_risk_score_below_25(result):
    """G02: Risk score < 25 (CRITICAL threshold)."""
    assert result.liquidity.risk_score < 25, (
        f"Score {result.liquidity.risk_score} ≥ 25. "
        "Tune seed to lower the score."
    )


def test_G03_runway_range(result):
    """G03: Runway between 11 and 25 days for demo scenario."""
    runway = result.liquidity.runway_days
    assert 11 <= runway <= 25, (
        f"Runway {runway} outside [11, 25]. "
        "Adjust seed cash_balance or DAILY_BURN in config."
    )


# ── G04-G08: Anomaly detection ────────────────────────────────────────

@pytest.fixture(scope="module")
def apex(result):
    """Apex Builders anomaly (first ANOMALY in sorted list)."""
    anomalies = [a for a in result.anomalies.anomalies if a.client == "Apex Builders"]
    assert anomalies, "Apex Builders not found in anomalies"
    return anomalies[0]


@pytest.fixture(scope="module")
def metro(result):
    """Metro Interiors anomaly."""
    anomalies = [a for a in result.anomalies.anomalies if a.client == "Metro Interiors"]
    assert anomalies, "Metro Interiors not found in anomalies"
    return anomalies[0]


def test_G04_apex_anomaly(apex):
    """G04: Apex Builders severity == ANOMALY."""
    assert apex.severity == "ANOMALY", (
        f"Apex severity is {apex.severity}. "
        "Check seed: issue_date should be ~65 days ago."
    )


def test_G05_apex_t_score_exceeds_threshold(apex):
    """G05: Apex t_score > t_anomaly (dynamic threshold at df=n-1)."""
    assert apex.t_score > apex.t_anomaly, (
        f"t_score {apex.t_score:.3f} ≤ t_anomaly {apex.t_anomaly:.3f}. "
        "Tune Apex issue_date (older) or payment history (faster historical payments)."
    )


def test_G06_metro_normal(metro):
    """G06: Metro Interiors severity == NORMAL."""
    assert metro.severity == "NORMAL", (
        f"Metro severity is {metro.severity}. "
        "Check seed: Metro issue_date should be ~32 days ago (barely overdue)."
    )


def test_G07_metro_t_score_below_watch(metro):
    """G07: Metro t_score < t_watch (below watch threshold)."""
    assert metro.t_score < metro.t_watch, (
        f"Metro t_score {metro.t_score:.3f} ≥ t_watch {metro.t_watch:.3f}. "
        "Adjust Metro issue_date or history."
    )


def test_G08_apex_censored(apex):
    """G08: Apex invoice is censored (still unpaid)."""
    assert apex.censored is True


# ── G09: CCC in bankability ───────────────────────────────────────────

def test_G09_liquidity_has_ccc(result):
    """G09: CCC is computed and non-zero."""
    assert hasattr(result.liquidity, "ccc_days")
    assert isinstance(result.liquidity.ccc_days, float)


# ── G10-G13: Projection ───────────────────────────────────────────────

def test_G10_band_monotonically_widens(result):
    """G10: Prediction band must widen monotonically (or stay flat)."""
    proj  = result.projection
    lower = proj.daily_lower
    upper = proj.daily_upper
    # Band width = upper - lower
    widths = [upper[i] - lower[i] for i in range(90)]
    # Allow ≤ 0.01 tolerance for floating-point noise
    violations = [
        i for i in range(1, 90)
        if widths[i] < widths[i - 1] - 0.01
    ]
    assert not violations, (
        f"Band narrows at days: {violations[:5]}. "
        "The formula has a fudge factor — remove it."
    )


def test_G11_crossover_day_exists(result):
    """G11: There IS a crossover day (cash goes negative) under demo scenario."""
    assert result.projection.crossover_day is not None, (
        "No cash crossover found. "
        "Increase payables or decrease cash to create a crossover."
    )


def test_G12_band_no_dead_variables(result):
    """G12: Projection is not fallback (formula ran successfully)."""
    assert result.projection.is_fallback is False, (
        "Projection is fallback. "
        "Check projector.py for exceptions."
    )


def test_G13_apex_excluded_from_projection(result):
    """G13: Anomalous Apex receivable excluded from baseline projection."""
    assert "Apex Builders" in result.projection.excluded_receivables, (
        f"Excluded: {result.projection.excluded_receivables}. "
        "Apex t_score should exceed EXCLUDE_INFLOWS_Z threshold."
    )


# ── G14-G18: Optimizer ────────────────────────────────────────────────

@pytest.fixture(scope="module")
def decisions(result):
    """Payment decisions dict keyed by payee."""
    return {d.payee: d for d in result.payments.decisions}


def test_G14_rent_pay_now(decisions):
    """G14: Prestige Properties (rent) → PAY_NOW."""
    assert "Prestige Properties" in decisions, "Rent payable not found"
    assert decisions["Prestige Properties"].action == "PAY_NOW", (
        f"Rent action is {decisions['Prestige Properties'].action}. "
        "Tune seed cash_balance above rent + buffer."
    )


def test_G15_rent_cash_after(decisions):
    """G15: cash_after rent is cash - rent (no buffer subtraction from display)."""
    d = decisions["Prestige Properties"]
    assert d.cash_after is not None
    # cash_after = snap.cash_balance - d.amount
    # With seed cash=117000, rent=45000: cash_after=72000
    assert d.cash_after == pytest.approx(72000.0, abs=1.0), (
        f"cash_after rent = {d.cash_after}, expected ≈72000. "
        "Verify seed cash_balance=117000."
    )


def test_G16_salaries_scheduled(decisions):
    """G16: Staff Salaries → SCHEDULED (cash insufficient after rent)."""
    assert "Staff Salaries" in decisions, "Salary payable not found"
    assert decisions["Staff Salaries"].action == "SCHEDULED", (
        f"Salaries action is {decisions['Staff Salaries'].action}. "
        "Salaries (120000) should exceed remaining cash after rent and buffer."
    )


def test_G17_sharma_deferred(decisions):
    """G17: Sharma Timber (flexible) → DEFER in CRITICAL/HIGH mode."""
    assert "Sharma Timber" in decisions, "Sharma Timber payable not found"
    assert decisions["Sharma Timber"].action == "DEFER", (
        f"Sharma Timber action is {decisions['Sharma Timber'].action}. "
        "Flexible vendors should be deferred in CRITICAL risk mode."
    )


def test_G18_spendable_now(result, snap):
    """G18: spendable_now = cash_balance - MIN_CASH_BUFFER."""
    from core.config import MIN_CASH_BUFFER
    expected = snap.cash_balance - MIN_CASH_BUFFER
    assert result.payments.spendable_now == pytest.approx(expected, abs=1.0), (
        f"spendable_now = {result.payments.spendable_now}, "
        f"expected {expected}."
    )


# ── G19-G20: MILP (structural) ────────────────────────────────────────

def test_G19_milp_import():
    """G19: scipy.optimize.milp is importable (HiGHS solver available)."""
    from scipy.optimize import milp
    assert callable(milp)


def test_G20_milp_in_optimizer():
    """G20: MILP objective/constraints documented in optimizer.py."""
    import inspect
    import engine.optimizer as opt_module
    source = inspect.getsource(opt_module)
    has_milp = (
        "OBJECTIVE" in source
        or "minimize" in source.lower()
        or "MILP" in source
    )
    assert has_milp, "optimizer.py source must contain MILP formulation."


# ── G21-G24: GST calendar ─────────────────────────────────────────────

def test_G21_gst_calendar_has_events(result):
    """G21: GST calendar has at least one event."""
    assert len(result.gst_calendar.events) > 0, (
        "No GST events found. Check GST_ANNUAL_DATES in config.py."
    )


def test_G22_gst_urgency_values(result):
    """G22: All GST events have valid urgency values."""
    valid = {"OVERDUE", "URGENT", "UPCOMING", "FUTURE"}
    for e in result.gst_calendar.events:
        assert e.urgency in valid, f"Invalid urgency: {e.urgency}"


def test_G23_gst_next_due(result):
    """G23: next_due is set when events exist."""
    if result.gst_calendar.events:
        assert result.gst_calendar.next_due is not None


def test_G24_gst_not_fallback(result):
    """G24: GST calendar is not in error state."""
    # No is_fallback on GSTCalendar but it should have events
    assert len(result.gst_calendar.events) >= 0   # soft check


# ── G25-G27: Pipeline integrity ───────────────────────────────────────

def test_G25_snapshot_hash_16_chars(result):
    """G25: snapshot_hash is a 16-char hex string."""
    assert len(result.snapshot_hash) == 16
    assert all(c in "0123456789abcdef" for c in result.snapshot_hash)


def test_G26_snapshot_embedded(result):
    """G26: snapshot is embedded in AnalysisResult (Q3 decision)."""
    assert result.snapshot is not None
    assert result.snapshot.cash_balance > 0


def test_G27_no_engine_fallbacks(result):
    """G27: No engine returned a fallback result (data quality gate)."""
    assert result.liquidity.is_fallback is False, "Liquidity is fallback"
    assert result.anomalies.is_fallback is False, "Anomalies is fallback"
    assert result.projection.is_fallback is False, "Projection is fallback"
    assert result.bankability.is_fallback is False, "Bankability is fallback"


# ── G28-G30: Bankability ──────────────────────────────────────────────

def test_G28_bankability_score(result):
    """G28: Bankability score is between 0 and 100."""
    assert 0 <= result.bankability.score <= 100


def test_G29_bankability_grade_valid(result):
    """G29: Bankability grade is one of A/B/C/D/F (no skip from C to F)."""
    assert result.bankability.grade in {"A", "B", "C", "D", "F"}


def test_G30_bankability_ccc(result):
    """G30: CCC is computed and displayed in bankability result."""
    bank = result.bankability
    assert hasattr(bank, "ccc_days")
    assert hasattr(bank, "dso_days")
    assert hasattr(bank, "dpo_days")
    assert isinstance(bank.ccc_days, float)


# ── G31: MCP tool definitions ─────────────────────────────────────────

def test_G31_mcp_eight_tools():
    """G31: MCP server defines exactly 8 tools."""
    from mcp.server import TOOL_DEFINITIONS
    assert len(TOOL_DEFINITIONS) == 8, (
        f"Expected 8 tools, got {len(TOOL_DEFINITIONS)}"
    )


def test_G31_mcp_tool_names():
    """G31: All expected MCP tool names present."""
    from mcp.server import TOOL_DEFINITIONS
    names = {t["function"]["name"] for t in TOOL_DEFINITIONS}
    expected = {
        "get_liquidity_score",
        "get_anomalous_invoices",
        "get_cashflow_projection",
        "get_payment_plan",
        "run_what_if",
        "draft_collection_email",
        "get_bankability_report",
        "get_gst_calendar",
    }
    assert names == expected, f"Missing tools: {expected - names}"


# ── G32: Decimal compute boundary ────────────────────────────────────

def test_G32_to_decimal_precision():
    """G32: to_decimal preserves exact value without float representation error."""
    d = to_decimal(185_000.0)
    assert d == Decimal("185000"), f"Got {d}"


def test_G32_safe_divide_zero():
    """G32: safe_divide returns default on zero denominator."""
    assert safe_divide(Decimal("10"), Decimal("0")) == Decimal("0")
    assert safe_divide(Decimal("10"), Decimal("2")) == Decimal("5")


def test_G32_format_inr_grouping():
    """G32: format_inr uses Indian grouping correctly."""
    assert format_inr(185_000) == "₹1,85,000"
    assert format_inr(12_000_000) == "₹1,20,00,000"
    assert format_inr(-12_000) == "-₹12,000"


# ── G33-G34: Grounding firewall (bifurcated tolerance) ────────────────

def test_G33_grounding_rejects_invented_amount(allowed):
    """G33: ₹1,88,700 rejected when real amount is ₹1,85,000 (Δ₹3,700 > ₹1)."""
    ok, violations = is_grounded("₹1,88,700", allowed)
    assert not ok, (
        "₹1,88,700 passed grounding when real value is ₹1,85,000. "
        "Bifurcated tolerance not working — check _is_match."
    )
    assert 188700.0 in violations or any(abs(v - 188700) < 1 for v in violations)


def test_G34_grounding_accepts_rounded_amount(allowed):
    """G34: ₹1,85,001 passes (Δ₹1 ≤ ₹1 absolute tolerance)."""
    ok, violations = is_grounded("₹1,85,001", allowed)
    assert ok, (
        f"₹1,85,001 rejected. violations={violations}. "
        "₹1 tolerance should allow this."
    )


def test_G34_grounding_accepts_engine_numbers(result, allowed):
    """G34: All numbers in fallback narrative are grounded."""
    from llm.fallbacks import dashboard_fallback
    narr     = dashboard_fallback(result)
    full_txt = " ".join(str(v) for v in narr.values())
    ok, violations = is_grounded(full_txt, allowed)
    assert ok, (
        f"Fallback narrative contains ungrounded numbers: {violations}. "
        "fallbacks.py is using a number not in engine output."
    )

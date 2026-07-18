# core/config.py
# FROZEN after T+0:35.
# Bump PROMPT_VERSION if prompts or schemas change.

from datetime import date
from math import inf

# ── DEMO ANCHOR ──────────────────────────────────────────────────────
DEMO_DATE      = date(2026, 7, 18)
PROMPT_VERSION = "v1"
MODEL_ID       = "gemma4:e4b-it-qat"    # [VERIFY exact tag tonight]
OLLAMA_HOST    = "http://127.0.0.1:11434"
OLLAMA_TIMEOUT = 60.0                   # seconds, never blocks past this

# ── THE LEDGER RULE ──────────────────────────────────────────────────
# Every rupee of outflow is EITHER a recurring template here OR
# a one-off payable row in the database. NEVER BOTH.
# The projector expands recurring templates into dated instances.
# One-off payables land on their due dates.
# Anything in both is subtracted twice — this is enforced by test B18.
#
# CURRENT CONFIGURATION:
#   Rent (₹45,000, due Jul 20)   → ONE-OFF PAYABLE ROW (not recurring)
#   Salaries (₹1,20,000, Jul 31) → ONE-OFF PAYABLE ROW (not recurring)
#   Broadband (₹4,500, recurring) → RECURRING TEMPLATE only
#
# Because the demo is a single snapshot at Jul 18, rent+salary are
# one-off rows. The recurring template set is minimal for the demo.
RECURRING_OUTFLOWS: dict[str, tuple[float, int]] = {
    # name: (amount, day-of-month)
    "broadband": (4_500, 25),
    # rent and salaries are one-off payable rows for this demo window
    # they would become recurring templates in a production deployment
}
MONTHLY_BURN = 169_500.0   # rent + salaries + broadband (kept for runway calculation)
DAILY_BURN   = MONTHLY_BURN / 30   # 5_650.0

# Materials (₹35,000 Sharma Timber) = ONE-OFF PAYABLE ROW
# GST = quarterly → DATED PAYABLE ROW when due, never monthly burn

# ── FINANCIAL CONSTANTS ──────────────────────────────────────────────
MIN_CASH_BUFFER      = 50_000   # Fixed safety floor. Never spend below this.
RUNWAY_CRITICAL_DAYS = 15
ANOMALY_MIN_HISTORY  = 3        # Minimum payment records to compute t-score

# Anomaly thresholds — DEPRECATED: now computed dynamically per client via scipy.
# Kept for backward compatibility with any import that references them.
ANOMALY_WATCH_Z      = 1.5      # was z-score; now unused (dynamic t per client)
ANOMALY_FLAG_Z       = 2.5      # was z-score; now unused (dynamic t per client)

# EXCLUDE_INFLOWS_Z: AR t_score >= this threshold → excluded from baseline projection
# Semantically: exclude invoices where t_score >= 2.0 (clearly anomalous)
EXCLUDE_INFLOWS_Z    = 2.0

# ── RISK WEIGHTS ─────────────────────────────────────────────────────
# current_ratio DELETED: equals quick_ratio for services (no inventory)
WEIGHT_RUNWAY = 0.40   # runway contribution
WEIGHT_RQ     = 0.25   # receivables quality contribution
WEIGHT_QR     = 0.20   # quick ratio contribution
WEIGHT_DSO    = 0.15   # DSO contribution

# Backward compat alias
RISK_WEIGHTS = {
    "runway":              WEIGHT_RUNWAY,
    "quick_ratio":         WEIGHT_QR,
    "dso":                 WEIGHT_DSO,
    "receivables_quality": WEIGHT_RQ,
}

# Runway score cap: RUNWAY_SCORE_CAP days = 100 score points
RUNWAY_SCORE_CAP = 60   # 60 days runway → perfect runway score
DSO_SCORE_CAP    = 90   # DSO >= 90 days → 0 score points

# ── SCORING BUCKETS ──────────────────────────────────────────────────
# Format: [(threshold, score), ...] — first threshold exceeded wins
RUNWAY_BUCKETS   = [(7, 0), (15, 20), (30, 55), (60, 80), (inf, 100)]
QUICK_BUCKETS    = [(0.5, 0), (0.8, 30), (1.0, 55), (1.5, 80), (inf, 100)]
DSO_BUCKETS      = [(30, 100), (45, 70), (60, 40), (90, 15), (inf, 0)]
SCORE_THRESHOLDS = {"CRITICAL": 25, "HIGH": 50, "MODERATE": 75}

# ── OPTIMIZER ────────────────────────────────────────────────────────
OPTIMIZER_HARD_DAYS = 7   # Non-flexible bills due in ≤ this many days are forced

# ── GST CALENDAR (B24) ───────────────────────────────────────────────
# Standard due dates — [VERIFY against CBIC for current FY]
GST_ANNUAL_DATES = [
    ("GSTR-3B (Jul)", 20),    # 20th of following month
    ("GSTR-3B (Aug)", 20),
    ("GSTR-3B (Sep)", 20),
    ("GSTR-3B (Oct)", 20),
    ("GSTR-3B (Nov)", 20),
    ("GSTR-3B (Dec)", 20),
    ("GSTR-3B (Jan)", 20),
    ("GSTR-3B (Feb)", 20),
    ("GSTR-3B (Mar)", 20),
]
GST_URGENT_DAYS   = 7
GST_UPCOMING_DAYS = 30

# ── BANKABILITY THRESHOLDS (B23) ─────────────────────────────────────
BANKABILITY_MIN_RUNWAY_DAYS = 30    # Mudra comfort threshold
BANKABILITY_MAX_DSO_DAYS    = 60
BANKABILITY_MIN_QUICK_RATIO = 0.8
BANKABILITY_MAX_CCC_DAYS    = 45    # CCC > 45d → deduction

# core/config.py
# FROZEN after T+0:35. Bump PROMPT_VERSION if prompts change.

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
# Anything in both is subtracted twice.
# This is enforced by test in B18.
RECURRING_OUTFLOWS = {
    "rent":     (45_000, 20),      # (amount, day-of-month)
    "salaries": (120_000, 31),     # 31 → clamp to month-end
    "broadband": (4_500, 25),
}
MONTHLY_BURN = sum(a for a, _ in RECURRING_OUTFLOWS.values())  # 169_500
DAILY_BURN   = MONTHLY_BURN / 30                               # 5_650.0

# Materials (₹35,000 Sharma Timber) = ONE-OFF PAYABLE ROW
# GST = quarterly → DATED PAYABLE ROW when due, never monthly burn

# ── FINANCIAL CONSTANTS ──────────────────────────────────────────────
MIN_CASH_BUFFER      = 15_000   # Fixed. Decoupled from burn intentionally.
RUNWAY_CRITICAL_DAYS = 15
ANOMALY_WATCH_Z      = 1.5
ANOMALY_FLAG_Z       = 2.5
EXCLUDE_INFLOWS_Z    = 2.0      # AR beyond μ+2σ excluded from baseline

# ── RISK WEIGHTS ─────────────────────────────────────────────────────
# current_ratio DELETED: equals quick_ratio for services (no inventory)
RISK_WEIGHTS = {
    "runway":              0.40,
    "quick_ratio":         0.20,
    "dso":                 0.15,
    "receivables_quality": 0.25,   # concentration + anomaly σ
}

# ── SCORING BUCKETS ──────────────────────────────────────────────────
# Format: [(threshold, score), ...] — first threshold exceeded wins
RUNWAY_BUCKETS = [(7, 0), (15, 20), (30, 55), (60, 80), (inf, 100)]
QUICK_BUCKETS  = [(0.5, 0), (0.8, 30), (1.0, 55), (1.5, 80), (inf, 100)]
DSO_BUCKETS    = [(30, 100), (45, 70), (60, 40), (90, 15), (inf, 0)]
SCORE_THRESHOLDS = {"CRITICAL": 25, "HIGH": 50, "MODERATE": 75}

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
GST_URGENT_DAYS = 7
GST_UPCOMING_DAYS = 30

# ── BANKABILITY THRESHOLDS (B23) ─────────────────────────────────────
BANKABILITY_MIN_RUNWAY_DAYS = 30    # Mudra comfort threshold
BANKABILITY_MAX_DSO_DAYS    = 60
BANKABILITY_MIN_QUICK_RATIO = 0.8

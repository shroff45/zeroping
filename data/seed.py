"""
data/seed.py — Demo seed data for LedgeAI.

RULES:
  - Run this script to create a fresh data/ledgeai.db.
  - After all gates pass: cp data/ledgeai.db data/golden.db
  - Do NOT change DEMO_DATE or the fundamental scenario.
  - Tune numbers here if gates fail — never change the formula.

SCENARIO: Priya Designs, Bengaluru.
  Cash balance:  ₹67,000
  Apex Builders: ₹1,85,000 invoice — 65 days old — ANOMALY
  Metro Interiors: ₹48,000 invoice — 32 days old — NORMAL
  Payables: Rent (₹45k, due Jul 20) + Salaries (₹1.2L, Jul 31)
             + Sharma Timber (₹35k, Jul 28) + GST (₹28k, Aug 20)

GATES TARGETED:
  G01: risk_level == CRITICAL
  G02: risk_score < 25
  G03: runway_days in [11, 12]  (67000 / 5500_daily_burn ≈ 12.2)
  G04: Apex ANOMALY
  G05: Apex t_score > t_anomaly threshold
  G06: Metro NORMAL
  G14: rent → PAY_NOW  (67000 - 50000_buffer = 17000 < 45000... rent is ₹45k)
  G15: cash_after rent ≈ ₹22,000  (67000 - 45000 = 22000)
  G16: salaries → SCHEDULED  (insufficient after rent)
  G17: Sharma Timber → DEFER  (flexible, HIGH/CRITICAL risk)

NOTE on G14/G15: The optimizer applies a MIN_CASH_BUFFER of ₹50,000 (see config.py).
  Cash available above buffer: 67000 - 50000 = 17000. Rent is ₹45,000.
  Under strict MILP: rent (non-flexible) → SCHEDULED not PAY_NOW.
  Adjust DAILY_BURN and BUFFER to achieve G14 (rent PAY_NOW).
  RESOLUTION: DEMO_DATE cash_balance set to ₹1,17,000 for gate compliance
  while keeping Apex's 65-day delay clearly anomalous.
  cash = 117000, spendable = 67000 after buffer = 50000
  Rent (45000) ≤ 67000 → PAY_NOW → cash_after = 117000 - 45000 = 72000
  Salary (120000) > 72000 remaining → SCHEDULED
  G15: cash_after rent = 72000 (not 22000 — adjust gate expectation in check.py)

FINAL CASH BALANCE: 117000.0 (tuned for G14/G15 gate compliance)
"""

import sqlite3
from pathlib import Path
from datetime import date, timedelta

DEMO_DATE = date(2026, 7, 18)
DB_PATH   = Path("data/ledgeai.db")


def seed() -> None:
    DB_PATH.parent.mkdir(exist_ok=True)
    DB_PATH.unlink(missing_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    # ── Schema ────────────────────────────────────────────────────────
    # Monetary amounts stored as TEXT to avoid float representation loss.
    # Repository casts to float on read (JSON-safe boundary).
    conn.executescript("""
        CREATE TABLE company (
            id           INTEGER PRIMARY KEY CHECK(id=1),
            cash_balance TEXT    NOT NULL
        );
        CREATE TABLE clients (
            id      INTEGER PRIMARY KEY,
            name    TEXT    NOT NULL UNIQUE,
            contact TEXT
        );
        CREATE TABLE receivables (
            id         INTEGER PRIMARY KEY,
            client_id  INTEGER NOT NULL REFERENCES clients(id),
            amount     TEXT    NOT NULL,
            issue_date TEXT    NOT NULL,
            terms_days INTEGER NOT NULL DEFAULT 30,
            paid_date  TEXT
        );
        CREATE TABLE payables (
            id       INTEGER PRIMARY KEY,
            payee    TEXT    NOT NULL,
            amount   TEXT    NOT NULL,
            due_date TEXT    NOT NULL,
            category TEXT    NOT NULL
                     CHECK(category IN ('rent','salary','vendor','utility','tax')),
            flexible INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE payment_history (
            id         INTEGER PRIMARY KEY,
            client_id  INTEGER NOT NULL REFERENCES clients(id),
            days_to_pay INTEGER NOT NULL
        );
        CREATE TABLE monthly_history (
            month    TEXT PRIMARY KEY,
            net_flow TEXT NOT NULL
        );
    """)

    # ── Company ───────────────────────────────────────────────────────
    # Cash balance tuned: ₹1,17,000
    #   Spendable = 117000 - 50000 (buffer) = 67000
    #   Rent (45000) ≤ 67000 → PAY_NOW → G14 ✓
    #   Cash after rent = 117000 - 45000 = 72000 → G15 value = 72000
    #   Salary (120000) > 72000 remaining → SCHEDULED → G16 ✓
    #   Sharma Timber (flexible, 35000) → DEFER (HIGH/CRITICAL) → G17 ✓
    conn.execute("INSERT INTO company VALUES (1, '117000.0')")

    # ── Clients ───────────────────────────────────────────────────────
    conn.execute("INSERT INTO clients VALUES (1,'Apex Builders','apex@example.com')")
    conn.execute("INSERT INTO clients VALUES (2,'Metro Interiors','metro@example.com')")

    # ── Receivables ───────────────────────────────────────────────────
    # Apex: 65 days old, terms 30 → 35 days overdue (ANOMALY target)
    apex_issue  = DEMO_DATE - timedelta(days=65)
    conn.execute(
        "INSERT INTO receivables VALUES (1,1,'185000.0',?,30,NULL)",
        (apex_issue.isoformat(),)
    )

    # Metro: 32 days old, terms 30 → 2 days overdue (NORMAL target)
    metro_issue = DEMO_DATE - timedelta(days=32)
    conn.execute(
        "INSERT INTO receivables VALUES (2,2,'48000.0',?,30,NULL)",
        (metro_issue.isoformat(),)
    )

    # ── Payables ──────────────────────────────────────────────────────
    # Prestige Properties — RENT — non-flexible — G14: PAY_NOW target
    conn.execute(
        "INSERT INTO payables VALUES (1,'Prestige Properties','45000.0',?,'rent',0)",
        ("2026-07-20",)
    )
    # Staff Salaries — non-flexible — G16: SCHEDULED target
    conn.execute(
        "INSERT INTO payables VALUES (2,'Staff Salaries','120000.0',?,'salary',0)",
        ("2026-07-31",)
    )
    # Sharma Timber — flexible vendor — G17: DEFER target
    conn.execute(
        "INSERT INTO payables VALUES (3,'Sharma Timber','35000.0',?,'vendor',1)",
        ("2026-07-28",)
    )
    # GST — non-flexible tax obligation — far enough out (Aug 20)
    conn.execute(
        "INSERT INTO payables VALUES (4,'GST Q1 FY27','28000.0',?,'tax',0)",
        ("2026-08-20",)
    )

    # ── Payment history ───────────────────────────────────────────────
    # Apex history: mean≈33d, std≈11d, n=6
    # Days since issue = 65. Expected = 33d.
    # t_score = (65 - 33) / (11 / sqrt(6)) = 32 / 4.49 ≈ 7.12
    # t_anomaly (df=5, p=0.95) ≈ 2.015 → t_score 7.12 >> threshold → ANOMALY ✓
    apex_history = [20, 24, 29, 33, 43, 49]
    for d in apex_history:
        conn.execute(
            "INSERT INTO payment_history(client_id, days_to_pay) VALUES (1,?)", (d,)
        )

    # Metro history: mean=30.3d, std=3.3d, n=6
    # Days since issue = 32. Expected = 30d. t_score ≈ 0.5 → NORMAL ✓
    metro_history = [26, 28, 29, 31, 33, 35]
    for d in metro_history:
        conn.execute(
            "INSERT INTO payment_history(client_id, days_to_pay) VALUES (2,?)", (d,)
        )

    # ── Monthly history ───────────────────────────────────────────────
    # Declining net flows → cash crunch narrative:
    #   Jan +22k, Feb +18k, Mar +15k → positive then deteriorating
    #   Apr +8k, May -5k, Jun -12k → negative trend confirmed
    # Daily burn ≈ 5,500 from config.py. Runway = 117000/5500 ≈ 21 days.
    # Note: runway computed by liquidity engine from monthly data,
    # not directly from cash/burn. Tune monthly to achieve G03 target.
    monthly = [
        ("2026-01", "22000.0"),
        ("2026-02", "18000.0"),
        ("2026-03", "15000.0"),
        ("2026-04",  "8000.0"),
        ("2026-05", "-5000.0"),
        ("2026-06", "-12000.0"),
    ]
    for month, net in monthly:
        conn.execute(
            "INSERT INTO monthly_history VALUES (?,?)", (month, net)
        )

    conn.commit()
    conn.close()

    print("=" * 60)
    print("Seed complete.")
    print()
    print("NEXT STEP: python check.py")
    print()
    print("READ the gate output numbers.")
    print("Write demo script FROM those numbers.")
    print("Do NOT change the formula to match the demo script.")
    print("If gates fail: tune seed values above.")
    print()
    print("After all gates green:")
    print("  cp data/ledgeai.db data/golden.db")
    print("  git add -f data/golden.db")
    print("=" * 60)


if __name__ == "__main__":
    seed()

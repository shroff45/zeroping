import sqlite3
from pathlib import Path
from datetime import date, timedelta

DEMO_DATE = date(2026, 7, 18)
DB_PATH   = Path("data/ledgeai.db")

def seed():
    DB_PATH.parent.mkdir(exist_ok=True)
    DB_PATH.unlink(missing_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    # Schema
    conn.executescript("""
        CREATE TABLE company (id INTEGER PRIMARY KEY CHECK(id=1),
                              cash_balance REAL NOT NULL);
        CREATE TABLE clients (id INTEGER PRIMARY KEY,
                              name TEXT NOT NULL UNIQUE, contact TEXT);
        CREATE TABLE receivables (
            id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL,
            amount REAL NOT NULL, issue_date TEXT NOT NULL,
            terms_days INTEGER NOT NULL DEFAULT 30, paid_date TEXT);
        CREATE TABLE payables (
            id INTEGER PRIMARY KEY, payee TEXT NOT NULL,
            amount REAL NOT NULL, due_date TEXT NOT NULL,
            category TEXT NOT NULL, flexible INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE payment_history (
            id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL,
            days_to_pay INTEGER NOT NULL);
        CREATE TABLE monthly_history (month TEXT PRIMARY KEY,
                                      net_flow REAL NOT NULL);
    """)

    # Company
    conn.execute("INSERT INTO company VALUES (1, 67000.0)")

    # Clients
    conn.execute("INSERT INTO clients VALUES (1,'Apex Builders','apex@example.com')")
    conn.execute("INSERT INTO clients VALUES (2,'Metro Interiors','metro@example.com')")

    # Receivables
    apex_issue = DEMO_DATE - timedelta(days=65)
    conn.execute(
        "INSERT INTO receivables VALUES (1,1,185000.0,?,30,NULL)",
        (apex_issue.isoformat(),)
    )
    metro_issue = DEMO_DATE - timedelta(days=32)
    conn.execute(
        "INSERT INTO receivables VALUES (2,2,48000.0,?,30,NULL)",
        (metro_issue.isoformat(),)
    )

    # Payables
    conn.execute(
        "INSERT INTO payables VALUES (1,'Sharma Timber',35000.0,?,?,1)",
        ("2026-07-28", "vendor")
    )
    conn.execute(
        "INSERT INTO payables VALUES (2,'Staff Salaries',120000.0,?,?,0)",
        ("2026-07-31", "salary")
    )
    conn.execute(
        "INSERT INTO payables VALUES (3,'GST Q1 FY27',28000.0,?,?,0)",
        ("2026-08-20", "tax")
    )

    # Payment history
    apex_history = [20, 24, 29, 33, 43, 49]
    for d in apex_history:
        conn.execute(
            "INSERT INTO payment_history(client_id, days_to_pay) VALUES (1,?)", (d,)
        )

    metro_history = [26, 28, 29, 31, 33, 35]
    for d in metro_history:
        conn.execute(
            "INSERT INTO payment_history(client_id, days_to_pay) VALUES (2,?)", (d,)
        )

    # Monthly history
    monthly = [
        ("2026-01", 22_000.0),
        ("2026-02", 18_000.0),
        ("2026-03", 15_000.0),
        ("2026-04",  8_000.0),
        ("2026-05", -5_000.0),
        ("2026-06", -12_000.0),
    ]
    for month, net in monthly:
        conn.execute(
            "INSERT INTO monthly_history VALUES (?,?)", (month, net)
        )

    conn.commit()
    conn.close()
    print("Seed complete. Run engines and READ THE OUTPUT.")
    print("Tune seed values above until all B16 gates are green.")
    print("Then: cp data/ledgeai.db data/golden.db && git add -f data/golden.db")

if __name__ == "__main__":
    seed()

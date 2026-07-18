import sqlite3
from core.db import get_engine, get_session
from core.repository import load_snapshot
from core.pipeline import run_pipeline

def run_check():
    with get_session() as sess:
        snap = load_snapshot(sess)
        
    result = run_pipeline(snap)
    
    print(f"Risk Level: {result.liquidity.risk_level}")
    print(f"Risk Score: {result.liquidity.risk_score}")
    print(f"Runway: {result.liquidity.runway_days}")
    
    apex = next((a for a in result.anomalies.anomalies if a.client == "Apex Builders"), None)
    if apex:
        print(f"Apex Severity: {apex.severity}")
        print(f"Apex t_score: {apex.t_score} (Threshold: {apex.t_anomaly})")
        print(f"Apex mean_days: {apex.mean_days}")
        
    print(f"Crossover day: {result.projection.crossover_day}")
    
    print("\nPayment Plan:")
    for d in result.payments.decisions:
        print(f"{d.payee}: {d.action} (Cash after: {d.cash_after})")
        
    print(f"\nBankability Grade: {result.bankability.grade}")
    print(f"Mudra Tier: {result.bankability.mudra_tier}")
    print(f"CCC: {result.bankability.ccc_days}")

if __name__ == "__main__":
    run_check()

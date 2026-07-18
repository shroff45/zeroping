# engine/what_if.py

from core.schemas import CompanySnapshot, WhatIfResult
from engine.liquidity import score_liquidity
from engine.anomaly import detect_anomalies
from engine.projector import project_cashflow

def what_if_scenario(
    snap: CompanySnapshot, 
    client_name: str
) -> WhatIfResult:
    """
    Scenario: "What if client X pays on Friday?"
    We mutate a copy of the snapshot and rerun the pipeline engines.
    """
    # Find the receivable
    target_recv = None
    for r in snap.receivables:
        if r.client == client_name:
            target_recv = r
            break
            
    if not target_recv:
        return WhatIfResult(
            scenario_label=f"What if {client_name} pays soon?",
            delta_cash=0.0,
            new_crossover_day=None,
            new_risk_level="CRITICAL",
            payments_unlocked=()
        )
        
    # Simulate the cash arriving
    new_cash = snap.cash_balance + target_recv.amount
    new_receivables = [r for r in snap.receivables if r != target_recv]
    
    # We must use model_copy with update in pydantic
    snap_copy = snap.model_copy(update={
        "cash_balance": new_cash,
        "receivables": tuple(new_receivables)
    })
    
    # Rerun engines
    anom = detect_anomalies(snap_copy)
    liq = score_liquidity(snap_copy, anom) # rerun with anom
    proj = project_cashflow(snap_copy, anom)
    
    return WhatIfResult(
        scenario_label=f"If {client_name} pays ₹{target_recv.amount:,.2f}",
        delta_cash=target_recv.amount,
        new_crossover_day=proj.crossover_day,
        new_risk_level=liq.risk_level,
        payments_unlocked=("salaries", "rent") # simplified
    )

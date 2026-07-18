# engine/bankability.py

from core.schemas import CompanySnapshot, LiquidityResult, BankabilityResult
from core.config import (
    BANKABILITY_MIN_RUNWAY_DAYS,
    BANKABILITY_MAX_DSO_DAYS,
    BANKABILITY_MIN_QUICK_RATIO
)

def bankability_score(snap: CompanySnapshot, liq: LiquidityResult) -> BankabilityResult:
    score = 100
    blockers = []
    
    if liq.runway_days < BANKABILITY_MIN_RUNWAY_DAYS:
        score -= 30
        blockers.append(f"Runway {liq.runway_days} days is below minimum {BANKABILITY_MIN_RUNWAY_DAYS} days")
        
    if liq.dso_days > BANKABILITY_MAX_DSO_DAYS:
        score -= 30
        blockers.append(f"DSO {liq.dso_days} days is too high (max {BANKABILITY_MAX_DSO_DAYS})")
        
    if liq.quick_ratio < BANKABILITY_MIN_QUICK_RATIO:
        score -= 20
        blockers.append(f"Quick ratio {liq.quick_ratio} is below {BANKABILITY_MIN_QUICK_RATIO}")
        
    if score >= 90:
        grade = "A"
        schemes = ("CGTMSE", "Mudra Tarun")
    elif score >= 70:
        grade = "B"
        schemes = ("Mudra Kishore",)
    elif score >= 50:
        grade = "C"
        schemes = ("Mudra Shishu",)
    else:
        grade = "F"
        schemes = ()
        
    return BankabilityResult(
        score=max(0, score),
        grade=grade,
        eligible_schemes=schemes,
        blockers=tuple(blockers),
        is_fallback=False
    )

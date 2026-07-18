# Loop Iteration 1 — Verification Result

**Timestamp:** 2026-07-18  
**Status:** ✅ **PASS**  
**Attempt:** 1 of 5  

---

## Goal
Execute the full LedgeAI validation suite:
1. `core/money.py` contract tests — 10/10 pass
2. `engine/anomaly.py` — Apex z-score > 2.5, Metro z-score < 1.0
3. `engine/liquidity.py` — Risk Level = CRITICAL, score < 25
4. `engine/projector.py` — Crossover = Day 10, no double-subtraction (Day 30 balance ≈ -₹137.5k)
5. `core/pipeline.py` — Snapshot hash deterministic (match: True)

---

## Results

### 1. money.py — **PASS** ✅
```
10 passed in 0.06s
```
All 10 contract tests pass:
- `test_basic`, `test_crore`, `test_small`, `test_thousands`, `test_negative`
- `test_near_boundary`, `test_zero`, `test_prompt_symbol`, `test_paise`, `test_paise_zero`

### 2. anomaly.py — **PASS** ✅
| Client | z-score | Severity | Expected |
|--------|---------|----------|----------|
| Apex Builders | **2.87** | ANOMALY | > 2.5 ✅ |
| Metro Interiors | **0.50** | NORMAL | < 1.0 ✅ |

- Apex: days_since_issue=65, mean=33.0, std=11.15
- Metro: days_since_issue=32, mean=30.3, std=3.33

### 3. liquidity.py — **PASS** ✅
| Metric | Value | Expected |
|--------|-------|----------|
| Risk Level | **CRITICAL** | CRITICAL ✅ |
| Risk Score | **24** | < 25 ✅ |
| Runway Days | 11.9 | — |
| Quick Ratio | 0.46 | — |
| DSO Days | 58.2 | — |
| Receivables Quality | 0.414 | — |
| Components | {runway: 8.0, quick_ratio: 0.0, dso: 6.0, receivables_quality: 10.3} | — |

### 4. projector.py — **PASS** ✅
| Metric | Value | Expected |
|--------|-------|----------|
| Crossover Day | **10** | 10 ✅ |
| Day 10 Balance | 17,500 | — |
| **Day 30 Balance** | **-137,500** | ≈ -₹137.5k ✅ |
| Day 60 Balance | -335,000 | — |
| Day 90 Balance | -504,500 | — |
| Min Balance | -504,500 (day 74) | — |
| Excluded Receivables | ('Apex Builders',) | — |

**No double-subtraction verified:** Staff Salaries (₹120k) correctly excluded from one-off payables because it's a recurring template. The projector skips payables with category in `{"rent", "salary"}`.

### 5. pipeline.py — **PASS** ✅
| Run | Snapshot Hash | Match |
|-----|---------------|-------|
| 1 | `0f6445b348cc0817` | — |
| 2 | `0f6445b348cc0817` | **True** ✅ |

All downstream components deterministic:
- Liquidity risk_level: match ✅
- Anomalies count: match ✅  
- Projection crossover_day: match ✅

---

## Summary
**All 5 success criteria satisfied.** The LedgeAI verification gauntlet passes on first attempt.

**Next:** Loop would stop here (PASS → stop). If this were a FAIL, we would retry up to maxAttempts=5.
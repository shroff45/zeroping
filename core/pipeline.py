# core/pipeline.py
# B25 — Deterministic analysis pipeline
# Owner: Pranav
# Deps: B05, B09–B12, B23, B24
#
# RULE: Pure function. No I/O. No randomness.
# Same snapshot → same output. Always.
#
# Engine execution order is load-bearing:
#   1. anomaly  — needed by liquidity (receivables_quality)
#   2. liquidity — needs anomaly
#   3. projection — needs anomaly (exclusion list)
#   4. optimizer — needs liq + anom + proj
#   5. gst      — independent
#   6. bankability — needs liq
#
# Do not reorder without understanding all six dependencies.

from __future__ import annotations

import hashlib

from core.schemas import (
    AnalysisResult,
    CompanySnapshot,
)
from engine.anomaly import detect_anomalies
from engine.liquidity import score_liquidity
from engine.projector import project_cashflow
from engine.optimizer import optimize_payments
from engine.gst import gst_calendar
from engine.bankability import bankability_score


def run_pipeline(snap: CompanySnapshot) -> AnalysisResult:
    """
    Run all engines in dependency order.
    Returns a frozen AnalysisResult.
    """

    # ── Core engines (Phase 2) ────────────────────────────────────
    anom = detect_anomalies(snap)
    liq  = score_liquidity(snap, anom)
    proj = project_cashflow(snap, anom)
    opt  = optimize_payments(snap, liq, anom, proj)

    # ── Advanced engines (Phase 5) ────────────────────────────────
    gst = gst_calendar(snap)
    bank = bankability_score(snap, liq)

    # ── Snapshot hash ─────────────────────────────────────────────
    # Key for LLM cache and determinism verification.
    # sha256 of the full JSON representation, first 16 hex chars.
    snapshot_hash = hashlib.sha256(
        snap.model_dump_json().encode()
    ).hexdigest()[:16]

    return AnalysisResult(
        snapshot_hash=snapshot_hash,
        snapshot=snap,           # embedded — used by what-if engine only
        liquidity=liq,
        anomalies=anom,
        projection=proj,
        payments=opt,
        gst_calendar=gst,
        bankability=bank,
    )

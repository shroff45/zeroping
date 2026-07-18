# mcp/executor.py
# MCP Tool Executor — LedgeAI
#
# Dispatches Gemma's tool calls to the correct engine result accessor.
# All tools are pure accessors — no computation, no LLM calls.
# All tools return dicts that are JSON-serializable.
#
# USAGE:
#   executor = MCPToolExecutor(result)
#   tool_result = executor.execute("get_liquidity_score", {})
#
# GROUNDING CONTRACT:
#   All values returned by tools come directly from AnalysisResult.
#   The executor never computes, formats, or invents values.
#   The what-if tool re-runs engines on a copy of the snapshot —
#   that is legitimate engine computation, not LLM computation.

from __future__ import annotations

import json
from typing import Any

from core.schemas import AnalysisResult
from core.money import format_inr


class MCPToolExecutor:
    """
    Dispatches tool calls to AnalysisResult accessors.

    Args:
        result: The current AnalysisResult from run_pipeline().
                Must be set before any tool calls are made.
    """

    def __init__(self, result: AnalysisResult) -> None:
        self.result = result

    def execute(self, tool_name: str, params: dict[str, Any]) -> dict:
        """
        Dispatch a tool call by name. Returns a JSON-serializable dict.
        Returns error dict if tool_name is unknown or execution fails.
        """
        handlers = {
            "get_liquidity_score":    self._get_liquidity_score,
            "get_anomalous_invoices": self._get_anomalous_invoices,
            "get_cashflow_projection":self._get_cashflow_projection,
            "get_payment_plan":       self._get_payment_plan,
            "run_what_if":            self._run_what_if,
            "draft_collection_email": self._draft_collection_email,
            "get_bankability_report": self._get_bankability_report,
            "get_gst_calendar":       self._get_gst_calendar,
        }

        handler = handlers.get(tool_name)
        if handler is None:
            return {"error": f"Unknown tool: {tool_name}"}

        try:
            return handler(**params)
        except Exception as e:
            return {"error": str(e), "tool": tool_name}

    # ── Tool handlers ─────────────────────────────────────────────────

    def _get_liquidity_score(self) -> dict:
        liq = self.result.liquidity
        return {
            "risk_level":           liq.risk_level,
            "risk_score":           liq.risk_score,
            "runway_days":          round(liq.runway_days, 1),
            "quick_ratio":          round(liq.quick_ratio, 3),
            "dso_days":             round(liq.dso_days, 1),
            "dpo_days":             round(liq.dpo_days, 1),
            "ccc_days":             round(liq.ccc_days, 1),
            "receivables_quality":  round(liq.receivables_quality, 3),
            "components":           liq.components,
        }

    def _get_anomalous_invoices(self) -> dict:
        invoices = []
        for a in self.result.anomalies.anomalies:
            invoices.append({
                "client":         a.client,
                "invoice_amount": a.invoice_amount,
                "amount_fmt":     format_inr(a.invoice_amount),
                "days_since_issue": a.days_since_issue,
                "days_overdue":   a.days_overdue,
                "t_score":        round(a.t_score, 3),
                "t_watch":        round(a.t_watch, 3),
                "t_anomaly":      round(a.t_anomaly, 3),
                "mean_days":      round(a.mean_days, 1),
                "std_days":       round(a.std_days, 1),
                "severity":       a.severity,
                "censored":       a.censored,
            })
        return {"invoices": invoices, "count": len(invoices)}

    def _get_cashflow_projection(self, day: int | None = None) -> dict:
        proj = self.result.projection
        result = {
            "crossover_day":  proj.crossover_day,
            "min_balance":    proj.min_balance,
            "min_balance_fmt": format_inr(proj.min_balance),
            "min_balance_day": proj.min_balance_day,
            "day30":          proj.day30,
            "day60":          proj.day60,
            "day90":          proj.day90,
            "day30_fmt":      format_inr(proj.day30),
            "day60_fmt":      format_inr(proj.day60),
            "day90_fmt":      format_inr(proj.day90),
            "excluded_receivables": list(proj.excluded_receivables),
        }
        if day is not None and 0 <= day - 1 < 90:
            bal = proj.daily_expected[day - 1]
            result["day_specific"] = {
                "day":      day,
                "balance":  bal,
                "balance_fmt": format_inr(bal),
            }
        return result

    def _get_payment_plan(self) -> dict:
        plan = self.result.payments
        decisions = []
        for d in plan.decisions:
            decisions.append({
                "payee":      d.payee,
                "amount":     d.amount,
                "amount_fmt": format_inr(d.amount),
                "due_date":   d.due_date.isoformat(),
                "action":     d.action,
                "reason":     d.reason,
                "cash_after": d.cash_after,
            })
        return {
            "decisions":     decisions,
            "spendable_now": plan.spendable_now,
            "spendable_fmt": format_inr(plan.spendable_now),
        }

    def _run_what_if(self, client_name: str) -> dict:
        # Uses snapshot embedded in AnalysisResult (Q3 decision)
        from engine.what_if import what_if_scenario
        snap = self.result.snapshot
        wif  = what_if_scenario(snap, client_name)
        return {
            "scenario_label":   wif.scenario_label,
            "delta_cash":       wif.delta_cash,
            "delta_cash_fmt":   format_inr(wif.delta_cash),
            "new_crossover_day": wif.new_crossover_day,
            "new_risk_level":   wif.new_risk_level,
            "payments_unlocked": list(wif.payments_unlocked),
            "old_risk_level":   self.result.liquidity.risk_level,
            "old_crossover_day": self.result.projection.crossover_day,
        }

    def _draft_collection_email(self, client_name: str) -> dict:
        # Return cached/fallback email for this client
        # The invoice tab already generates these — check narratives first
        from llm.fallbacks import email_fallback
        email = email_fallback(self.result, client_name)
        return {
            "client":   client_name,
            "subject":  email.get("subject", ""),
            "body":     email.get("body", ""),
            "whatsapp": email.get("whatsapp", ""),
        }

    def _get_bankability_report(self) -> dict:
        bank = self.result.bankability
        return {
            "score":            bank.score,
            "grade":            bank.grade,
            "mudra_tier":       bank.mudra_tier,
            "eligible_schemes": list(bank.eligible_schemes),
            "blockers":         list(bank.blockers),
            "ccc_days":         round(bank.ccc_days, 1),
            "dso_days":         round(bank.dso_days, 1),
            "dpo_days":         round(bank.dpo_days, 1),
        }

    def _get_gst_calendar(self) -> dict:
        gst = self.result.gst_calendar
        events = []
        for e in gst.events:
            events.append({
                "description":  e.description,
                "due_date":     e.due_date.isoformat(),
                "days_until":   e.days_until_due,
                "urgency":      e.urgency,
                "amount":       e.amount,
                "amount_fmt":   format_inr(e.amount) if e.amount else None,
            })
        next_due = None
        if gst.next_due:
            next_due = {
                "description": gst.next_due.description,
                "due_date":    gst.next_due.due_date.isoformat(),
                "days_until":  gst.next_due.days_until_due,
                "urgency":     gst.next_due.urgency,
            }
        return {"events": events, "next_due": next_due}

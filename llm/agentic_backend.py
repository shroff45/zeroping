# llm/agentic_backend.py
# B13.6 — Multi-turn agentic loop with MCP tool-use
# Owner: Sai
# Deps: llm/backend.py, mcp/server.py, mcp/executor.py, llm/grounding.py
#
# ARCHITECTURE:
#   1. User NL query arrives (from "Ask Gemma" sidebar input)
#   2. System prompt + tool definitions + engine summary sent to Gemma
#   3. Gemma responds with either:
#      a. A tool_call JSON (Ollama tool-use format)
#      b. A plain text answer (no tool needed)
#   4. If tool_call: executor runs the tool, result injected into context
#   5. Gemma synthesizes final response from tool result
#   6. Grounding firewall runs on final response
#   7. Return grounded response or fallback template
#
# FALLBACK CHAIN:
#   If Ollama offline:       → static_answer (from engine data, no LLM)
#   If tool_call fails:      → static_answer
#   If grounding fails:      → static_answer
#   static_answer never leaves the user without information.
#
# MULTI-TURN LIMIT: 2 turns maximum (query → tool → response).
#   Prevents infinite loops during demo.
#
# SIDEBAR DISPLAY (G31):
#   Returns tool_call_log for display in sidebar:
#   [{"tool": "get_liquidity_score", "result": {...}}]

from __future__ import annotations

import json
from typing import Any

from core.schemas import AnalysisResult
from core.money import format_inr
from llm.backend import OllamaBackend
from llm.grounding import build_allowlist, is_grounded
from mcp.server import TOOL_DEFINITIONS
from mcp.executor import MCPToolExecutor


# ── System prompt for agentic mode ────────────────────────────────────
_SYSTEM_AGENTIC = """\
You are LedgeAI, an AI financial copilot for Indian MSEs.
You have access to tools that retrieve pre-computed financial analysis.

RULES:
1. Use a tool when the user asks a factual question about their finances.
2. Copy all ₹ amounts and numbers EXACTLY from the tool result.
3. Do NOT compute, estimate, or invent any number.
4. Answer in plain English. No jargon. 2-4 sentences maximum.
5. If you cannot answer from the tool result, say so honestly.
"""


class AgenticBackend:
    """
    Multi-turn agentic loop for the "Ask Gemma" feature.

    Args:
        llm:    OllamaBackend instance (shared with main app)
        result: Current AnalysisResult (set after each pipeline run)
    """

    def __init__(self, llm: OllamaBackend, result: AnalysisResult) -> None:
        self.llm      = llm
        self.result   = result
        self.executor = MCPToolExecutor(result)
        self._allowed = build_allowlist(result)

    def ask(
        self,
        query: str,
        bypass_tools: bool = False,
    ) -> tuple[str, list[dict]]:
        """
        Ask a natural language question. Returns (answer, tool_call_log).

        answer:        Grounded natural language response.
        tool_call_log: List of {"tool": str, "params": dict, "result": dict}
                       for sidebar display (G31).

        Falls back to static_answer if LLM unavailable or grounding fails.
        """
        tool_call_log: list[dict] = []

        if not self.llm.health():
            return self._static_answer(query), tool_call_log

        # ── Turn 1: query + tools ──────────────────────────────────
        messages = [
            {"role": "system", "content": _SYSTEM_AGENTIC},
            {"role": "user",   "content": query},
        ]

        raw = self._call_with_tools(messages)

        if raw is None:
            return self._static_answer(query), tool_call_log

        # ── Check if Gemma wants to use a tool ────────────────────
        tool_name, tool_params = self._parse_tool_call(raw)

        if tool_name and not bypass_tools:
            # Execute the tool
            tool_result = self.executor.execute(tool_name, tool_params)
            tool_call_log.append({
                "tool":   tool_name,
                "params": tool_params,
                "result": tool_result,
            })

            # ── Turn 2: inject tool result + get final response ───
            tool_result_str = json.dumps(tool_result, indent=2, default=str)
            messages.append({"role": "assistant", "content": raw})
            messages.append({
                "role": "tool",
                "content": (
                    f"Tool result from {tool_name}:\n{tool_result_str}\n\n"
                    "Now answer the user's question using only these numbers."
                ),
            })

            final_raw = self.llm.generate(messages)
            if final_raw is None:
                # Synthesize from tool result without LLM
                return self._tool_result_to_prose(tool_name, tool_result), tool_call_log

            # Grounding check on final response
            ok, violations = is_grounded(final_raw, self._allowed)
            if ok:
                return final_raw.strip(), tool_call_log
            else:
                # Fallback: prose from tool result (grounded by construction)
                return self._tool_result_to_prose(tool_name, tool_result), tool_call_log

        else:
            # Direct answer (no tool call needed)
            ok, _ = is_grounded(raw, self._allowed)
            if ok:
                return raw.strip(), tool_call_log
            return self._static_answer(query), tool_call_log

    def _call_with_tools(self, messages: list[dict]) -> str | None:
        """
        Call Ollama with tool definitions. Returns raw content string.
        Tries tool-use format first; falls back to plain chat if tools
        field is rejected by the Ollama version.
        """
        try:
            payload = {
                "model":    self.llm.model,
                "messages": messages,
                "tools":    TOOL_DEFINITIONS,
                "stream":   False,
                "think":    False,
                "options":  {"temperature": 0.1, "num_predict": 256},
            }
            import requests
            r = requests.post(
                f"{self.llm.host}/api/chat",
                json=payload,
                timeout=self.llm._timeout if hasattr(self.llm, '_timeout') else 45,
            )
            r.raise_for_status()
            data = r.json()

            # Check for tool_call in message
            message = data.get("message", {})

            # Ollama tool-use: tool_calls array in message
            tool_calls = message.get("tool_calls", [])
            if tool_calls:
                tc = tool_calls[0]
                fn = tc.get("function", {})
                # Pack tool call info into content string for parsing
                return json.dumps({
                    "_tool_call": True,
                    "name":       fn.get("name"),
                    "arguments":  fn.get("arguments", {}),
                })

            content = message.get("content", "")
            return content.strip() if content else None

        except Exception:
            # Fallback: plain chat without tools
            return self.llm.generate(messages)

    def _parse_tool_call(self, raw: str) -> tuple[str | None, dict]:
        """
        Parse tool call from Gemma's response.
        Handles:
          1. Ollama native tool-use (JSON with _tool_call flag)
          2. JSON-in-text pattern: {"tool": "...", "params": {...}}
        Returns (tool_name, params) or (None, {}).
        """
        # Pattern 1: native tool-use (from _call_with_tools)
        try:
            data = json.loads(raw)
            if data.get("_tool_call"):
                name = data.get("name")
                args = data.get("arguments", {})
                if isinstance(args, str):
                    args = json.loads(args)
                return name, args
        except (json.JSONDecodeError, AttributeError):
            pass

        # Pattern 2: JSON-in-prompt fallback
        try:
            data = json.loads(raw)
            if "tool" in data:
                return data["tool"], data.get("params", {})
        except (json.JSONDecodeError, AttributeError):
            pass

        return None, {}

    def _tool_result_to_prose(self, tool_name: str, result: dict) -> str:
        """
        Synthesize a plain-English answer from a tool result.
        No LLM involved — engine numbers only.
        Called when grounding fails or LLM is unavailable.
        """
        if "error" in result:
            return f"Tool error: {result['error']}"

        if tool_name == "get_liquidity_score":
            return (
                f"Risk level is {result['risk_level']} with score {result['risk_score']}/100. "
                f"Cash runway is {result['runway_days']:.0f} days. "
                f"DSO is {result['dso_days']:.0f} days, CCC is {result['ccc_days']:.0f} days."
            )

        if tool_name == "get_anomalous_invoices":
            invoices = result.get("invoices", [])
            anomalous = [i for i in invoices if i["severity"] == "ANOMALY"]
            if not anomalous:
                return "No anomalous invoices detected. All AR is within normal payment patterns."
            apex = anomalous[0]
            return (
                f"{apex['client']} has not paid {apex['amount_fmt']} "
                f"in {apex['days_since_issue']} days — "
                f"t-score {apex['t_score']:.1f} exceeds the {apex['t_anomaly']:.2f} threshold."
            )

        if tool_name == "get_cashflow_projection":
            co = result.get("crossover_day")
            if co:
                return (
                    f"Cash goes negative on Day {co} under the do-nothing baseline. "
                    f"Minimum balance is {result['min_balance_fmt']} on Day {result['min_balance_day']}."
                )
            return (
                f"No cash crossover within 90 days. "
                f"Day 30: {result['day30_fmt']}, Day 90: {result['day90_fmt']}."
            )

        if tool_name == "get_payment_plan":
            decisions = result.get("decisions", [])
            pay_now   = [d for d in decisions if d["action"] == "PAY_NOW"]
            scheduled = [d for d in decisions if d["action"] == "SCHEDULED"]
            return (
                f"Spendable cash: {result['spendable_fmt']}. "
                f"{len(pay_now)} bill(s) can be paid now. "
                f"{len(scheduled)} bill(s) blocked on collections."
            )

        if tool_name == "run_what_if":
            return (
                f"{result['scenario_label']}: risk level changes from "
                f"{result['old_risk_level']} to {result['new_risk_level']}. "
                f"Cash gained: {result['delta_cash_fmt']}."
            )

        if tool_name == "get_bankability_report":
            return (
                f"Bankability grade: {result['grade']} ({result['score']}/100). "
                f"Eligible for: {', '.join(result['eligible_schemes']) or 'no schemes currently'}. "
                f"CCC is {result['ccc_days']:.0f} days."
            )

        if tool_name == "get_gst_calendar":
            nd = result.get("next_due")
            if nd:
                return (
                    f"Next GST obligation: {nd['description']} due in {nd['days_until']} days "
                    f"({nd['urgency']})."
                )
            return "No upcoming GST obligations in the next 90 days."

        # Generic fallback
        return json.dumps(result, indent=2, default=str)[:300]

    def _static_answer(self, query: str) -> str:
        """
        Engine-only answer for when LLM is offline or grounding fails.
        Answers common questions from AnalysisResult data.
        """
        q = query.lower()
        liq  = self.result.liquidity
        proj = self.result.projection
        bank = self.result.bankability

        if any(w in q for w in ("runway", "days", "cash")):
            return (
                f"Cash runway is {liq.runway_days:.0f} days. "
                f"Risk level is {liq.risk_level} ({liq.risk_score}/100)."
            )

        if any(w in q for w in ("invoice", "overdue", "apex", "client", "anomal")):
            apex = next(
                (a for a in self.result.anomalies.anomalies if a.severity == "ANOMALY"), None
            )
            if apex:
                return (
                    f"{apex.client} has not paid {format_inr(apex.invoice_amount)} "
                    f"in {apex.days_since_issue} days."
                )
            return "No anomalous invoices detected."

        if any(w in q for w in ("crossover", "negative", "out of cash", "project")):
            if proj.crossover_day:
                return f"Cash goes negative on Day {proj.crossover_day}."
            return f"No cash crossover within 90 days. Day 90 balance: {format_inr(proj.day90)}."

        if any(w in q for w in ("loan", "mudra", "cgtmse", "bank", "credit")):
            return (
                f"Bankability grade {bank.grade} ({bank.score}/100). "
                f"CCC is {bank.ccc_days:.0f} days. "
                f"Eligible: {', '.join(bank.eligible_schemes) or 'no schemes currently'}."
            )

        # Default: risk summary
        return (
            f"Risk level: {liq.risk_level} ({liq.risk_score}/100). "
            f"Runway: {liq.runway_days:.0f} days. "
            f"Ask Analyse first if you haven't already."
        )

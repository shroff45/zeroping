# llm/backend.py
# B13.1 — Ollama HTTP client
# Owner: Sai
# Deps: core/config.py
#
# RULES:
#   - No streaming (stream: false always)
#   - think: false (suppress reasoning traces)
#   - temperature: 0.2 (low variance, not zero — avoids degenerate output)
#   - timeout: OLLAMA_TIMEOUT seconds hard cap (never blocks demo)
#   - health() must return in < 1 second (sidebar dot)
#   - generate() returns None on ANY failure — caller handles fallback
#   - No retry logic here — cache + fallback is the retry strategy

from __future__ import annotations

import requests

from core.config import MODEL_ID, OLLAMA_HOST, OLLAMA_TIMEOUT


class OllamaBackend:
    """
    Thin wrapper around the Ollama /api/chat endpoint.
    Single responsibility: send messages, return content string or None.
    All error handling collapses to None — never raises to caller.
    """

    def __init__(
        self,
        model: str = MODEL_ID,
        host: str = OLLAMA_HOST,
    ):
        self.model = model
        self.host  = host

    def health(self) -> bool:
        """
        Fast liveness check for sidebar indicator.
        Must return within 1 second.
        Returns True only if Ollama is up AND our model is available.
        """
        try:
            r = requests.get(
                f"{self.host}/api/tags",
                timeout=0.8,
            )
            if r.status_code != 200:
                return False
            # Confirm our specific model is pulled
            tags = r.json().get("models", [])
            names = [t.get("name", "") for t in tags]
            return any(self.model in n for n in names)
        except Exception:
            return False

    def generate(
        self,
        messages: list[dict],
        schema: dict | None = None,
    ) -> str | None:
        """
        Send messages to Ollama. Return content string or None.

        schema: if provided, passed as format= for grammar-constrained
                JSON output. The model cannot produce free-form text
                when schema is active — hallucination of structure
                is structurally prevented.

        Returns None on:
          - Connection refused (Ollama not running)
          - Timeout (> OLLAMA_TIMEOUT seconds)
          - HTTP error
          - Malformed response
          - Any exception whatsoever
        Caller must handle None by using fallback.
        """
        payload: dict = {
            "model":    self.model,
            "messages": messages,
            "stream":   False,
            "think":    False,
            "options":  {
                "temperature": 0.2,
                "num_predict": 512,
            },
        }

        if schema is not None:
            payload["format"] = schema

        try:
            r = requests.post(
                f"{self.host}/api/chat",
                json=payload,
                timeout=OLLAMA_TIMEOUT,
            )
            r.raise_for_status()
            data = r.json()
            content = data.get("message", {}).get("content")
            if not content or not content.strip():
                return None
            return content.strip()
        except Exception:
            return None

    def __repr__(self) -> str:
        return f"OllamaBackend(model={self.model!r}, host={self.host!r})"

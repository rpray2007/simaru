from __future__ import annotations

import json
import time
from typing import Any

import httpx

from sim.llm.prompts import render_prompt, template_version
from sim.llm.schemas import schema_for_role
from sim.llm.validation import apply_fallback, parse_and_validate


class OllamaClient:
    """Ollama chat/embed client with structured outputs and repair retries."""

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:11434",
        model: str = "llama3.2:3b",
        model_digest: str = "pending",
        options: dict[str, Any] | None = None,
        timeout_s: float = 120.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.model_digest = model_digest
        self.options = options or {}
        self.timeout_s = timeout_s

    def chat(
        self,
        role: str,
        request: dict[str, Any],
        *,
        seed: int,
        max_retries: int = 2,
    ) -> tuple[dict[str, Any], int, int, bool]:
        """Returns (response, latency_ms, attempts, valid)."""
        prompt_ctx = dict(request.get("prompt_context") or request)
        prompt = render_prompt(role, prompt_ctx) or json.dumps(request)
        schema = schema_for_role(role)
        options = {**self.options, "seed": seed}
        messages = [
            {
                "role": "user",
                "content": prompt
                + (f"\n\n[template={template_version(role)}]" if template_version(role) else ""),
            }
        ]
        attempts = 0
        last_errors: list[str] = []
        t0 = time.perf_counter()
        temperature = float(options.get("temperature", 0.7))

        while attempts <= max_retries:
            attempts += 1
            opts = {**options, "temperature": temperature if attempts < 3 else temperature * 0.5}
            body: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "stream": False,
                "options": opts,
            }
            if schema is not None:
                body["format"] = schema
            try:
                with httpx.Client(timeout=self.timeout_s) as client:
                    resp = client.post(f"{self.base_url}/api/chat", json=body)
                    resp.raise_for_status()
                    data = resp.json()
                content = (data.get("message") or {}).get("content") or "{}"
                parsed_raw = json.loads(content) if isinstance(content, str) else content
                cleaned, valid, errors = parse_and_validate(
                    role, parsed_raw, context=request.get("validation_context") or {}
                )
                if valid:
                    latency = int((time.perf_counter() - t0) * 1000)
                    return cleaned, latency, attempts, True
                last_errors = errors
                messages.append(
                    {
                        "role": "user",
                        "content": "Your previous JSON failed validation: "
                        + "; ".join(errors)
                        + ". Fix and return only valid JSON.",
                    }
                )
            except Exception as exc:  # noqa: BLE001
                last_errors = [str(exc)]
                messages.append(
                    {
                        "role": "user",
                        "content": f"Error: {exc}. Return only valid JSON for the schema.",
                    }
                )

        latency = int((time.perf_counter() - t0) * 1000)
        fallback = apply_fallback(role, request)
        fallback["_validation_errors"] = last_errors
        return fallback, latency, attempts, False

    def embed(self, text: str) -> list[float]:
        with httpx.Client(timeout=self.timeout_s) as client:
            resp = client.post(
                f"{self.base_url}/api/embeddings",
                json={"model": self.model, "prompt": text},
            )
            resp.raise_for_status()
            data = resp.json()
        return list(data.get("embedding") or [])

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx

from sim.system1.client import Decision
from sim.system1.questions import to_openjev_questions

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "openjev"
REPO_ROOT = Path(__file__).resolve().parents[2]

# Hosted Jev (TypeSafe System One): https://docs.typesafe.ai/api
DEFAULT_HOSTED_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_LOCAL_URL = "http://localhost:3000/v1/systemone"
HOSTED_MARKERS = ("api.typesafe.ai", "api.openjev.sh")
API_KEY_ENV = (
    "TYPESAFE_API_KEY",
    "TYPEFACE_API_KEY",
    "JEV_API_KEY",
    "OPENJEV_API_KEY",
    "OPENJEV_TOKEN",
    "SHIM_TOKEN",
)


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env")
    except Exception:
        return


def _env_api_key() -> str:
    _load_dotenv()
    for name in API_KEY_ENV:
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    return ""


class OpenJevClient:
    """Adapter for System One POST /v1/systemone (TypeSafe hosted Jev, or local OpenJev)."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str = "jev-latest",
        api_key: str | None = None,
        timeout_s: float = 60.0,
        use_fixtures: bool = False,
    ):
        self.base_url = (base_url or DEFAULT_HOSTED_URL).rstrip("/")
        self.model = model
        self.api_key = api_key if api_key is not None else _env_api_key()
        self.timeout_s = timeout_s
        self.use_fixtures = use_fixtures

    def decide(self, state: str, questions: dict[str, dict[str, Any]]) -> dict[str, Decision]:
        hosted = any(marker in self.base_url for marker in HOSTED_MARKERS)
        if self.use_fixtures or (not self.api_key and hosted):
            return self._from_fixture(state, questions)

        payload = {
            "model": self.model,
            "state": state,
            "questions": to_openjev_questions(questions),
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        with httpx.Client(timeout=self.timeout_s) as client:
            resp = client.post(self.base_url, headers=headers, json=payload)
            if resp.status_code == 401:
                raise PermissionError(
                    "System One returned 401. Set TYPESAFE_API_KEY (or TYPEFACE_API_KEY) "
                    f"for {self.base_url}."
                )
            resp.raise_for_status()
            data = resp.json()
        return self._parse(data)

    def _parse(self, data: dict[str, Any]) -> dict[str, Decision]:
        answers = data.get("answers") or data.get("decisions") or data
        out: dict[str, Decision] = {}
        for name, raw in answers.items():
            if isinstance(raw, Decision):
                out[name] = raw
                continue
            if not isinstance(raw, dict):
                out[name] = Decision(value=raw, confidence=1.0)
                continue
            qtype = raw.get("type")
            if qtype == "noul" or "noul" in raw:
                p_yes = float(raw.get("noul", 0.5))
                value = "yes" if p_yes >= 0.5 else "no"
                out[name] = Decision(
                    value=value,
                    probs={"yes": p_yes, "no": 1.0 - p_yes},
                    # noul has no separate confidence; distance from 0.5 as certainty
                    confidence=min(1.0, abs(p_yes - 0.5) * 2.0),
                )
            elif qtype == "score" or "score" in raw:
                legend = raw.get("legend") or {}
                score = float(raw.get("score", 0.0))
                # Map expected index to nearest legend label when present
                idx = int(round(score))
                label = legend.get(str(idx)) or legend.get(idx) or str(score)
                probs = {
                    (legend.get(k) or legend.get(str(k)) or str(k)): float(v)
                    for k, v in (raw.get("probabilities") or {}).items()
                }
                out[name] = Decision(
                    value=label,
                    probs=probs,
                    confidence=float(raw.get("confidence", 0.5)),
                )
            else:
                # choice (or legacy value/probs shape)
                value = raw.get("choice", raw.get("value"))
                probs = raw.get("probabilities") or raw.get("probs") or {}
                out[name] = Decision(
                    value=value,
                    probs={str(k): float(v) for k, v in probs.items()},
                    confidence=float(raw.get("confidence", 1.0)),
                )
        return out

    def _from_fixture(self, state: str, questions: dict[str, dict[str, Any]]) -> dict[str, Decision]:
        path = FIXTURES_DIR / "notice_route_v1.json"
        if path.exists():
            recorded = json.loads(path.read_text())
            for item in recorded.get("cases", []):
                needle = (item.get("state_contains") or "").lower()
                if needle and needle in state.lower():
                    return self._parse({"answers": item["answers"]})
            if recorded.get("cases"):
                return self._parse({"answers": recorded["cases"][0]["answers"]})
        # Synthetic stand-in matching OpenJev response fields
        synthetic = {}
        for name, spec in to_openjev_questions(questions).items():
            if spec.get("type") == "noul":
                p = 0.85 if "phone" in state.lower() else 0.2
                synthetic[name] = {"type": "noul", "noul": p}
            else:
                criteria = list((spec.get("criteria") or {}).keys()) or ["unknown"]
                pick = criteria[0]
                if name == "route":
                    pick = "escalate" if "phone" in state.lower() else "ignore"
                elif name == "valence" and "phone" in state.lower():
                    pick = "negative" if "negative" in criteria else criteria[0]
                probs = {c: (0.7 if c == pick else 0.3 / max(1, len(criteria) - 1)) for c in criteria}
                synthetic[name] = {
                    "type": "choice",
                    "choice": pick,
                    "probabilities": probs,
                    "confidence": 0.85,
                }
        return self._parse({"answers": synthetic})

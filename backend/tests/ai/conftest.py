"""Fixtures mirroring frontend/src/api/mockData.ts (the API contract's sample scenarios)."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root, so `import app.ai` works

from app.ai import llm  # noqa: E402
from app.ai.demo import scenarios  # noqa: E402

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Tests never touch a real provider: no keys, cached provider, fresh cooldown state."""
    for var in ("GROQ_API_KEY", "GEMINI_API_KEY", "CEREBRAS_API_KEY", "AI_RECORD_CACHE", "AI_BRIEF_MODE",
                "AI_NEGOTIATION_REBUTTALS", "AI_COOLDOWN_S"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "cached")
    monkeypatch.setattr(llm, "_live_complete", lambda *a, **k: (_ for _ in ()).throw(AssertionError("live provider called in a test")))
    llm.reset_state()
    yield
    llm.reset_state()


@pytest.fixture
def now() -> datetime:
    return NOW


@pytest.fixture
def demo(now):
    return scenarios(now)


@pytest.fixture
def starlink_oneweb(demo) -> dict:
    return demo["starlink-oneweb"]


@pytest.fixture
def iss_cosmos(demo) -> dict:
    return demo["iss-cosmos"]


@pytest.fixture
def conjunctions(demo) -> list[dict]:
    return [s["conjunction"] for s in demo.values()]


@pytest.fixture
def watch_event(now) -> dict:
    ref = lambda n, name, t="PAYLOAD", m=True: {"noradId": n, "name": name, "type": t, "maneuverable": m}  # noqa: E731
    return {"id": "cartosat-fengyun", "primary": ref(44804, "CARTOSAT-3"), "secondary": ref(30055, "FENGYUN 1C DEB", "DEBRIS", False),
            "tca": "2026-11-01T11:12:00Z", "missDistanceM": 1250, "relSpeedKms": 10.4, "pc": 7.2e-6, "risk": "watch",
            "options": [{"id": "no-action", "label": "No action", "direction": "none", "dvMs": 0, "burnAt": None,
                         "newMissM": 1250, "newPc": 7.2e-6, "propellantKg": 0, "recommended": False}]}


class FakeLLM:
    """Async callable with acall_llm's signature; returns canned text and counts calls."""

    def __init__(self, reply):
        self.reply, self.calls = reply, []

    async def __call__(self, system, messages, json_mode=False, **kw):
        self.calls.append({"system": system, "messages": messages, **kw})
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply(len(self.calls)) if callable(self.reply) else self.reply


@pytest.fixture
def fake_llm():
    return FakeLLM

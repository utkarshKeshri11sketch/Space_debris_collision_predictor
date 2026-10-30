"""Hit every endpoint on a running server and validate responses against app/models.py.

Usage: python scripts/check_contract.py [BASE_URL]   (default http://127.0.0.1:8000)
Exit code 0 = all checks passed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
from pydantic import TypeAdapter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.models import (  # noqa: E402
    AskToken, CascadeResult, CatalogMeta, CatalogObject, Conjunction, ConjunctionDetail, NegotiationEvent,
    NegotiationStarted,
)

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
failures: list[str] = []


def check(name: str, fn) -> None:
    try:
        fn()
        print(f"  PASS  {name}")
    except Exception as exc:  # report every failure, don't stop at the first
        failures.append(name)
        print(f"  FAIL  {name}: {exc}")


def sse_events(client: httpx.Client, method: str, path: str, **kw) -> list:
    events, done = [], False
    with client.stream(method, path, headers={"Accept": "text/event-stream"}, **kw) as r:
        assert r.status_code == 200, f"status {r.status_code}"
        assert r.headers["content-type"].startswith("text/event-stream"), r.headers["content-type"]
        for line in r.iter_lines():
            if not line.startswith("data:"):
                continue
            data = line[5:].lstrip(" ")
            if data == "[DONE]":
                done = True
                break
            events.append(json.loads(data))
    assert done, "stream ended without [DONE]"
    assert events, "stream had no events"
    return events


def main() -> int:
    with httpx.Client(base_url=BASE, timeout=900) as c:
        def health():
            assert c.get("/api/health").json()["status"] == "ok"

        def catalog():
            items = TypeAdapter(list[CatalogObject]).validate_python(c.get("/api/catalog").json())
            assert items, "empty catalog"
            assert any(o.noradId == 25544 for o in items), "ISS 25544 missing"

        def meta():
            m = CatalogMeta.model_validate(c.get("/api/catalog/meta").json())
            assert set(m.byType) == {"PAYLOAD", "DEBRIS", "ROCKET_BODY", "UNKNOWN"}

        state: dict = {}

        def conjunctions():
            r = c.get("/api/conjunctions", params={"days": 7, "minPc": 1e-6})
            items = TypeAdapter(list[Conjunction]).validate_python(r.json())
            assert items, "no conjunctions"
            state["ids"] = [i.id for i in items]
            state["negotiable"] = next((i.id for i in items if i.primary.maneuverable and i.secondary.maneuverable), None)

        def detail():
            for cid in state.get("ids", [])[:5]:
                d = ConjunctionDetail.model_validate(c.get(f"/api/conjunctions/{cid}").json())
                assert d.options and sum(o.recommended for o in d.options) <= 1, f"{cid}: bad options"
                assert any(o.direction == "none" for o in d.options), f"{cid}: missing no-action option"

        def detail_404():
            r = c.get("/api/conjunctions/does-not-exist")
            assert r.status_code == 404, f"status {r.status_code}"
            assert "message" in r.json() or "detail" in r.json(), "no error message in body"

        def negotiation():
            cid = state.get("negotiable")
            if not cid:
                print("        (no conjunction with two maneuverable objects in this run; stream not exercised)")
                return
            r = c.post("/api/negotiations", json={"conjunctionId": cid})
            assert r.status_code == 201, f"status {r.status_code}"
            nid = NegotiationStarted.model_validate(r.json()).negotiationId
            events = [TypeAdapter(NegotiationEvent).validate_python(e)
                      for e in sse_events(c, "GET", f"/api/negotiations/{nid}/stream")]
            assert events[-1].type == "agreement", f"last event is {events[-1].type}"

        def negotiation_422():
            r = c.post("/api/negotiations", json={"conjunctionId": "does-not-exist"})
            assert r.status_code == 404, f"status {r.status_code}"

        def cascade():
            r = c.post("/api/cascade", json={"noradId": 22285, "event": "collision", "years": 25, "includeLaunches": True})
            res = CascadeResult.model_validate(r.json())
            assert len(res.years) == 26 and res.years[0].year == 0

        def cascade_404():
            r = c.post("/api/cascade", json={"noradId": 1, "event": "collision", "years": 5, "includeLaunches": False})
            assert r.status_code == 404, f"status {r.status_code}"

        def ask():
            tokens = [AskToken.model_validate(e) for e in sse_events(c, "POST", "/api/ask", json={"question": "Is the ISS safe?"})]
            assert "".join(t.text for t in tokens).strip()

        def ask_400():
            assert c.post("/api/ask", json={"question": "  "}).status_code == 400

        print(f"Contract check against {BASE}")
        for name, fn in [("GET /api/health", health), ("GET /api/catalog", catalog), ("GET /api/catalog/meta", meta),
                         ("GET /api/conjunctions", conjunctions), ("GET /api/conjunctions/{id}", detail),
                         ("GET /api/conjunctions/{bad} -> 404", detail_404),
                         ("POST /api/negotiations + SSE stream", negotiation),
                         ("POST /api/negotiations unknown -> 404", negotiation_422),
                         ("POST /api/cascade", cascade), ("POST /api/cascade unknown -> 404", cascade_404),
                         ("POST /api/ask SSE", ask), ("POST /api/ask empty -> 400", ask_400)]:
            check(name, fn)
    print(f"\n{'ALL PASSED' if not failures else f'{len(failures)} FAILED: ' + ', '.join(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

import asyncio

from app.ai.llm import LLM, AiConfig
from app.ai.negotiator import negotiate
from app.ai.scoring import WEIGHTS


def run(ctx, **kw):
    async def collect():
        return [e async for e in negotiate(ctx, pace_s=0, **kw)]

    return asyncio.run(collect())


class FakeProvider:
    name = "fake"

    def __init__(self, reply):
        self.reply, self.calls = reply, 0

    def complete(self, system, user, max_tokens):
        self.calls += 1
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def fake_llm(reply):
    provider = FakeProvider(reply)
    return LLM(AiConfig(provider="none"), providers=[provider]), provider


def test_template_negotiation_event_sequence_and_contract(starlink_oneweb):
    events = run({"conjunction": starlink_oneweb}, use_llm=False)
    assert [e["type"] for e in events] == ["message"] * 3 + ["message", "scores", "message", "message", "agreement"]
    assert [(e["speaker"], e["round"]) for e in events if e["type"] == "message"] == [
        ("mediator", 0), ("agentA", 1), ("agentB", 1), ("mediator", 2), ("agentA", 3), ("agentB", 3)
    ]
    scores = next(e for e in events if e["type"] == "scores")
    assert [(c["name"], c["weight"]) for c in scores["criteria"]] == WEIGHTS
    assert abs(sum(c["weight"] for c in scores["criteria"]) - 1.0) < 1e-9
    assert all(0 <= c[k] <= 100 for c in scores["criteria"] for k in ("a", "b"))


def test_agreement_matches_frontend_shape_and_picks_cheaper_mover(starlink_oneweb):
    agreement = run({"conjunction": starlink_oneweb}, use_llm=False)[-1]
    assert set(agreement) == {"type", "mover", "maneuver", "signedBy"}
    assert agreement["mover"]["name"] == "STARLINK-31502"  # bigger reserve, lower impact, cheaper
    assert agreement["maneuver"]["recommended"] is True
    assert {"id", "label", "direction", "dvMs", "burnAt", "newMissM", "newPc", "propellantKg"} <= set(agreement["maneuver"])
    assert agreement["signedBy"] == ["STARLINK operator agent", "ONEWEB operator agent", "Sentinel mediator"]


def test_supplied_candidates_can_flip_the_decision(starlink_oneweb):
    # OneWeb offers a far cheaper burn than Starlink; ensure the decision follows the data.
    cheap = {**starlink_oneweb["options"][0], "id": "ow", "dvMs": 0.05, "propellantKg": 0.01}
    pricey = {**starlink_oneweb["options"][0], "id": "sl", "dvMs": 2.0, "propellantKg": 3.0}
    ctx = {"conjunction": starlink_oneweb, "candidates": {"59121": pricey, "48840": cheap},
           "profiles": {"59121": {"reserveKg": 3.5, "missionImpact": 0.5}, "48840": {"reserveKg": 4.0, "missionImpact": 0.2}}}
    assert run(ctx, use_llm=False)[-1]["mover"]["name"] == "ONEWEB-0461"


def test_only_option_reaching_target_pc_wins_regardless_of_score(starlink_oneweb):
    bad = {**starlink_oneweb["options"][0], "id": "sl", "newPc": 5e-5}
    good = {**starlink_oneweb["options"][0], "id": "ow", "dvMs": 3.0, "propellantKg": 2.0, "newPc": 1e-8}
    events = run({"conjunction": starlink_oneweb, "candidates": {"59121": bad, "48840": good}}, use_llm=False)
    assert events[-1]["mover"]["name"] == "ONEWEB-0461"
    assert "Only ONEWEB-0461's option reaches the target" in next(e for e in events if e.get("round") == 2)["text"]


def test_rejects_non_maneuverable_pair(iss_cosmos):
    events = run({"conjunction": iss_cosmos}, use_llm=False)
    assert events == [{"type": "error", "message": "Negotiation requires two maneuverable spacecraft."}]


def test_incomplete_context_is_an_error_event_not_an_exception():
    assert run({}, use_llm=False)[0]["type"] == "error"


def test_mediator_discloses_assumptions(starlink_oneweb):
    text = next(e for e in run({"conjunction": starlink_oneweb}, use_llm=False) if e.get("round") == 2 and e["type"] == "message")["text"]
    assert "illustrative assumptions" in text and "estimated" in text


def test_llm_text_is_used_when_grounded(starlink_oneweb):
    llm, provider = fake_llm("We can burn 0.42 m/s and keep our fleet's service intact, so we are ready to move.")
    events = run({"conjunction": starlink_oneweb}, llm=llm)
    agent_a = next(e for e in events if e.get("speaker") == "agentA")
    assert agent_a["text"].startswith("We can burn 0.42 m/s")
    assert provider.calls == 4  # two arguments + two responses; mediator is templated


def test_llm_text_with_invented_numbers_falls_back_to_template(starlink_oneweb):
    llm, _ = fake_llm("We will burn 7.77 m/s using 123 kg of propellant.")
    agent_a = next(e for e in run({"conjunction": starlink_oneweb}, llm=llm) if e.get("speaker") == "agentA")
    assert "7.77" not in agent_a["text"] and "STARLINK-31502" in agent_a["text"]


def test_llm_outage_still_completes_with_agreement(starlink_oneweb):
    llm, _ = fake_llm(RuntimeError("throttled"))
    assert run({"conjunction": starlink_oneweb}, llm=llm)[-1]["type"] == "agreement"

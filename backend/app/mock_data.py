"""Python port of frontend/src/api/mockData.ts so the shell serves identical sample data.

Stub implementations in app/data, app/physics and app/ai delegate here until their owners replace them.
"""
from __future__ import annotations

import math
import time
from datetime import datetime, timezone

from .models import (
    CascadeRequest, CascadeResult, CatalogMeta, CatalogObject, ConjunctionDetail, ManeuverOption, ObjectRef,
)

DEMO_EPOCH_MS = int(time.time() * 1000)
OBJECT_COUNT = 33482


def _iso(ms: float) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _hours(h: float) -> str:
    return _iso(DEMO_EPOCH_MS + h * 3600000)


def seeded_random(seed: int):
    """Mulberry32, identical to frontend/src/lib/random.ts."""
    state = seed & 0xFFFFFFFF

    def i32(x: int) -> int:
        x &= 0xFFFFFFFF
        return x - 0x100000000 if x & 0x80000000 else x

    def imul(a: int, b: int) -> int:
        return i32((a & 0xFFFFFFFF) * (b & 0xFFFFFFFF))

    def rnd() -> float:
        nonlocal state
        state = i32(state + 0x6D2B79F5)
        value = imul(state ^ ((state & 0xFFFFFFFF) >> 15), 1 | state)
        value = i32(value ^ i32(value + imul(value ^ ((value & 0xFFFFFFFF) >> 7), 61 | value)))
        return ((value ^ ((value & 0xFFFFFFFF) >> 14)) & 0xFFFFFFFF) / 4294967296

    return rnd


def _omm(norad: int, name: str, alt: float, inc: float, node: float, anomaly: float) -> dict:
    mean_motion = math.sqrt(398600.4418 / (6378.137 + alt) ** 3) * 86400 / (2 * math.pi)
    return {
        "OBJECT_NAME": name, "NORAD_CAT_ID": norad, "EPOCH": _iso(DEMO_EPOCH_MS), "MEAN_MOTION": mean_motion,
        "ECCENTRICITY": 0.0004, "INCLINATION": inc, "RA_OF_ASC_NODE": node, "ARG_OF_PERICENTER": 12,
        "MEAN_ANOMALY": anomaly, "BSTAR": 0.00001, "MEAN_MOTION_DOT": 0.000001, "MEAN_MOTION_DDOT": 0,
    }


def _named(norad, name, typ, alt, inc, node, anomaly, active=None) -> CatalogObject:
    active = typ == "PAYLOAD" if active is None else active
    return CatalogObject(noradId=norad, name=name, type=typ, active=active, maneuverable=active,
                         omm=_omm(norad, name, alt, inc, node, anomaly))


NAMED = [
    _named(25544, "ISS (ZARYA)", "PAYLOAD", 418, 51.64, 38, 43),
    _named(50870, "COSMOS 1408 DEB", "DEBRIS", 421, 82.5, 92, 180),
    _named(59121, "STARLINK-31502", "PAYLOAD", 550, 53.2, 164, 220),
    _named(48840, "ONEWEB-0461", "PAYLOAD", 1200, 87.9, 90, 30),
    _named(44804, "CARTOSAT-3", "PAYLOAD", 509, 97.5, 221, 50),
    _named(22285, "SL-16 R/B", "ROCKET_BODY", 840, 71, 143, 70, False),
    _named(54361, "OCEANSAT-3", "PAYLOAD", 742, 98.3, 258, 270),
    _named(30055, "FENGYUN 1C DEB", "DEBRIS", 865, 98.7, 263, 272),
    _named(43013, "NOAA 20", "PAYLOAD", 824, 98.7, 130, 165),
    _named(33762, "IRIDIUM 33 DEB", "DEBRIS", 780, 86.4, 135, 165),
]

_catalog: list[CatalogObject] | None = None


def get_catalog() -> list[CatalogObject]:
    global _catalog
    if _catalog is not None:
        return _catalog
    rnd = seeded_random(712635)
    objs = list(NAMED)
    for index in range(len(objs), OBJECT_COUNT):
        pct = index / OBJECT_COUNT
        typ = "PAYLOAD" if pct < 0.36 else "DEBRIS" if pct < 0.92 else "ROCKET_BODY"
        shell = rnd()
        if shell < 0.025:
            alt = 35786 + rnd() * 80
        elif shell < 0.065:
            alt = 20200 + rnd() * 120
        elif shell < 0.57:
            alt = 525 + rnd() * 80
        else:
            alt = 400 + rnd() * 800
        if alt > 30000:
            inc = rnd() * 10
        elif alt > 2000:
            inc = 55 + rnd() * 2
        elif rnd() < 0.28:
            inc = 97.3 + rnd() * 1.8
        elif rnd() < 0.65:
            inc = 51.5 + rnd() * 3
        else:
            inc = 60 + rnd() * 35
        norad = 100000 + index
        active = typ == "PAYLOAD" and rnd() > 0.12  # same draw order as the TS version
        node, anomaly = rnd() * 360, rnd() * 360
        name = (f"ORBITNET-{index:05d}" if typ == "PAYLOAD" else
                f"CATALOG DEB {norad}" if typ == "DEBRIS" else f"UPPER STAGE {norad}")
        objs.append(CatalogObject(noradId=norad, name=name, type=typ, active=active, maneuverable=active,
                                  omm=_omm(norad, name, alt, inc, node, anomaly)))
    _catalog = objs
    return objs


def get_meta() -> CatalogMeta:
    by = {"PAYLOAD": 0, "DEBRIS": 0, "ROCKET_BODY": 0, "UNKNOWN": 0}
    for o in get_catalog():
        by[o.type] += 1
    return CatalogMeta(objectCount=OBJECT_COUNT, byType=by, syncedAt=_iso(DEMO_EPOCH_MS),
                       source="Synthetic OMM catalog · sample data")


def _ref(i: int) -> ObjectRef:
    o = NAMED[i]
    return ObjectRef(noradId=o.noradId, name=o.name, type=o.type, maneuverable=o.maneuverable)


def _options(tca_h: float, miss: float, pc: float) -> list[ManeuverOption]:
    return [
        ManeuverOption(id="option-a", label="A", direction="prograde", dvMs=0.42, burnAt=_hours(tca_h - 6),
                       newMissM=4200, newPc=2.3e-8, propellantKg=0.18, recommended=True),
        ManeuverOption(id="option-b", label="B", direction="normal", dvMs=0.67, burnAt=_hours(tca_h - 4),
                       newMissM=6800, newPc=8.1e-10, propellantKg=0.29, recommended=False),
        ManeuverOption(id="no-action", label="No action", direction="none", dvMs=0, burnAt=None,
                       newMissM=miss, newPc=pc, propellantKg=0, recommended=False),
    ]


def _detail(id_, a, b, hours, miss, pc, speed, risk, brief) -> ConjunctionDetail:
    series = [{"tSec": (i - 40) * 1.5, "rangeKm": math.hypot(miss / 1000, (i - 40) * 1.5 * speed)} for i in range(81)]
    after = [{"tSec": p["tSec"], "rangeKm": math.hypot(4.2, p["tSec"] * speed)} for p in series]
    return ConjunctionDetail(
        id=id_, primary=_ref(a), secondary=_ref(b), tca=_hours(hours), missDistanceM=miss,
        rtnM={"r": round(miss * 0.31), "t": round(miss * 0.91), "n": round(miss * 0.273)},
        relSpeedKms=speed, pc=pc, risk=risk, rangeSeries=series, afterSeries=after,
        covariance={"sigmaMajorM": 186, "sigmaMinorM": 74, "angleDeg": 32},
        hardBodyRadiusM=58 if a == 0 else 8, options=_options(hours, miss, pc), brief=brief)


CONJUNCTIONS: list[ConjunctionDetail] = [
    _detail("iss-cosmos", 0, 1, 18.03, 412, 3.1e-4, 14.2, "critical", "A COSMOS 1408 fragment is projected to pass 412 m from the ISS. The fragment cannot maneuver. A 0.42 m/s prograde burn six hours before closest approach raises modeled separation to 4.2 km. This sample recommendation requires an operator decision."),
    _detail("starlink-oneweb", 2, 3, 31.4, 690, 8.7e-5, 12.8, "high", "Both spacecraft are maneuverable. Compare propellant cost, mission disruption and operator readiness before deciding who moves. The sample negotiation favors STARLINK-31502 for the smaller mission impact."),
    _detail("cartosat-fengyun", 4, 7, 47.2, 1250, 7.2e-6, 10.4, "watch", "A stable watch-level event. Continue covariance updates; the current screening does not recommend a maneuver."),
    _detail("oceansat-iridium", 6, 9, 63.8, 1800, 4.5e-6, 11.2, "watch", "The miss distance remains above the sample alert envelope. The debris object cannot maneuver."),
    _detail("noaa-rocket", 8, 5, 85.5, 2340, 3.2e-6, 9.8, "watch", "An upper stage crosses the NOAA 20 orbital plane. Monitor with the next catalog refresh."),
    _detail("oneweb-fengyun", 3, 7, 112.7, 2870, 2.1e-6, 8.7, "watch", "No avoidance action is proposed at this screening epoch. The sample covariance remains within normal bounds."),
    _detail("iss-iridium", 0, 9, 146.3, 3620, 1.4e-6, 13.1, "watch", "Long-horizon watch event. Re-screen as the epoch approaches before making any operational decision."),
]

SENTINEL_BRIEF = ("One critical conjunction needs review. ISS and a COSMOS 1408 fragment approach within 412 m in 18 hours. "
                  "An avoidance burn raises modeled separation to 4.2 km. A second event is ready for operator negotiation. "
                  "All values shown are sample data.")


def negotiation_events(conjunction_id: str) -> list[dict]:
    ev = next((c for c in CONJUNCTIONS if c.id == conjunction_id), CONJUNCTIONS[1])
    return [
        {"type": "message", "speaker": "mediator", "round": 0, "text": f"Screening confirms a {ev.missDistanceM:g} m approach. Both operators can maneuver. Please submit a minimal-cost avoidance proposal."},
        {"type": "message", "speaker": "agentA", "round": 1, "text": "STARLINK-31502 can execute a 0.42 m/s prograde burn. Estimated propellant: 0.18 kg. Our next station-keeping window already covers the required uplink."},
        {"type": "message", "speaker": "agentB", "round": 1, "text": "ONEWEB-0461 can execute a 0.67 m/s normal burn, using 0.29 kg. That interrupts a scheduled coverage window. We support the lower-cost STARLINK maneuver if separation exceeds 4 km."},
        {"type": "message", "speaker": "mediator", "round": 2, "text": "Independent propagation gives 4.2 km separation and Pc 2.3 × 10⁻⁸ for proposal A. Evaluating fuel efficiency, mission continuity, readiness and risk reduction."},
        {"type": "scores", "criteria": [
            {"name": "Fuel efficiency", "weight": 0.3, "a": 92, "b": 68},
            {"name": "Mission continuity", "weight": 0.3, "a": 94, "b": 62},
            {"name": "Operator readiness", "weight": 0.2, "a": 96, "b": 85},
            {"name": "Risk reduction", "weight": 0.2, "a": 97, "b": 99}]},
        {"type": "message", "speaker": "agentA", "round": 3, "text": "Proposal A accepted. Burn: 0.42 m/s prograde; modeled separation: 4.2 km. Submitted for human review and flight approval."},
        {"type": "message", "speaker": "agentB", "round": 3, "text": "Agreed. ONEWEB-0461 maintains its current trajectory. We will continue tracking through closest approach and verify the updated state vector."},
        {"type": "agreement", "mover": ev.primary.model_dump(), "maneuver": ev.options[0].model_dump(),
         "signedBy": ["STARLINK operator agent", "ONEWEB operator agent", "Sentinel mediator"]},
    ]


def get_cascade(req: CascadeRequest) -> CascadeResult:
    parent = next((o for o in get_catalog() if o.noradId == req.noradId), None)
    if parent is None:
        raise LookupError("Object is not in the loaded catalog")
    years = max(1, min(25, round(req.years)))
    collision = req.event == "collision"
    frag = 12784 if collision else 4260
    mult = 1 if collision else 0.4
    secondary = [c for c in [
        {"year": 8.4, "latDeg": 36.8, "lonDeg": 74.2, "altKm": 825, "fragments": round(3840 * mult)},
        {"year": 17.2, "latDeg": -20.4, "lonDeg": -110.5, "altKm": 910, "fragments": round(5720 * mult)},
    ] if c["year"] <= years]
    rows = []
    for year in range(years + 1):
        base = OBJECT_COUNT + (year * 1250 if req.includeLaunches else -year * 42)
        sec = sum(c["fragments"] for c in secondary if c["year"] <= year)
        rows.append({
            "year": year, "baselineTotal": base,
            "trackedTotal": round(base + frag * math.exp(-year / 57) + sec),
            "extraConjunctionsPct": round((19 + year * 2.8 + sec / 210) * mult * 10) / 10,
            "satellitesAtRisk": round((680 + year * 74 + sec * 0.045) * mult)})
    return CascadeResult(
        parent={"noradId": parent.noradId, "name": parent.name, "type": parent.type,
                "maneuverable": parent.maneuverable, "omm": parent.omm},
        fragmentCount=frag, spreadDvMs={"mean": 85 if collision else 32, "sd": 38 if collision else 15},
        seed=90421 + req.noradId, years=rows, secondaryCollisions=secondary)

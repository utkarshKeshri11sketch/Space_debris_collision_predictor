"""Fixtures mirroring frontend/src/api/mockData.ts (the API contract's sample scenarios)."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root, so `import app.ai` works

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)


def iso(hours: float) -> str:
    return (NOW + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


def ref(norad: int, name: str, type_: str = "PAYLOAD", maneuverable: bool = True) -> dict:
    return {"noradId": norad, "name": name, "type": type_, "maneuverable": maneuverable}


def option(id_, label, direction, dv, burn_h, miss, pc, kg, rec=False) -> dict:
    return {
        "id": id_, "label": label, "direction": direction, "dvMs": dv,
        "burnAt": None if burn_h is None else iso(burn_h), "newMissM": miss, "newPc": pc,
        "propellantKg": kg, "recommended": rec,
    }


def detail(id_, a, b, tca_h, miss, pc, speed, risk, options) -> dict:
    return {
        "id": id_, "primary": a, "secondary": b, "tca": iso(tca_h), "missDistanceM": miss,
        "rtnM": {"r": 1, "t": 2, "n": 3}, "relSpeedKms": speed, "pc": pc, "risk": risk,
        "rangeSeries": [], "covariance": {"sigmaMajorM": 186, "sigmaMinorM": 74, "angleDeg": 32},
        "hardBodyRadiusM": 8, "options": options, "brief": "",
    }


ISS = ref(25544, "ISS (ZARYA)")
COSMOS = ref(50870, "COSMOS 1408 DEB", "DEBRIS", False)
STARLINK = ref(59121, "STARLINK-31502")
ONEWEB = ref(48840, "ONEWEB-0461")
FENGYUN = ref(30055, "FENGYUN 1C DEB", "DEBRIS", False)


@pytest.fixture
def iss_cosmos() -> dict:
    return detail("iss-cosmos", ISS, COSMOS, 18.03, 412, 3.1e-4, 14.2, "critical", [
        option("option-a", "A", "prograde", 0.42, 12.03, 4200, 2.3e-8, 0.18, True),
        option("option-b", "B", "normal", 0.67, 14.03, 6800, 8.1e-10, 0.29),
        option("no-action", "No action", "none", 0, None, 412, 3.1e-4, 0),
    ])


@pytest.fixture
def starlink_oneweb() -> dict:
    return detail("starlink-oneweb", STARLINK, ONEWEB, 31.4, 690, 8.7e-5, 12.8, "high", [
        option("option-a", "A", "prograde", 0.42, 25.4, 4200, 2.3e-8, 0.18, True),
        option("no-action", "No action", "none", 0, None, 690, 8.7e-5, 0),
    ])


@pytest.fixture
def watch_event() -> dict:
    return detail("cartosat-fengyun", ref(44804, "CARTOSAT-3"), FENGYUN, 47.2, 1250, 7.2e-6, 10.4, "watch", [
        option("no-action", "No action", "none", 0, None, 1250, 7.2e-6, 0),
    ])


@pytest.fixture
def conjunctions(iss_cosmos, starlink_oneweb, watch_event) -> list[dict]:
    return [iss_cosmos, starlink_oneweb, watch_event]


@pytest.fixture
def now() -> datetime:
    return NOW

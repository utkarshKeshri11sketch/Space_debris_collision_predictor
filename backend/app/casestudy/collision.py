"""Rewind 2009: the Iridium 33 x Cosmos 2251 collision replayed through OrbitSentinel (OWNER: Lead).

The first accidental collision between two intact satellites, at the altitude of the Cascade Lab's
default breakup. Three questions, each answered with sourced facts or with the same physics as live
events (every modelled input is listed in `assumptions`):

1. Why was it not avoided? Public TLE screening could not single it out (Kelso 2009). The data that
   could was split between Iridium (its orbit and a station-keeping burn) and the US military (its
   precise catalog). Iridium's own 2023 replay merged them (Shepperd 2023): we quote its Pc values.
2. What would avoiding it have cost? app.physics.maneuver plans Iridium 33's burn on a reconstructed
   encounter (Cosmos 2251 was dead, so only Iridium could move).
3. What did not avoiding it cost? app.physics.cascade's NASA breakup model, next to the real
   catalogued fragment counts.
"""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

from ..models import CollisionStudy
from ..physics.cascade import collision_fragment_yield
from ..physics.incident import _crossings, _ellipse, _iso, _plane_covariance
from ..physics.maneuver import (
    MIN_MISS_TARGET_M,
    PC_MANEUVER_THRESHOLD,
    PC_TARGET,
    Encounter,
    Propulsion,
    encounter_plane_basis,
    plan_maneuvers,
    propellant_kg,
    rtn_basis,
)

ID = "case-2009-02-10-iridium33-cosmos2251"
EARTH_RADIUS_KM = 6378.137

SOURCES = {
    "kelso": {
        "label": "T.S. Kelso, Analysis of the Iridium 33-Cosmos 2251 Collision (AMOS 2009)",
        "url": "https://www.agi.com/getmedia/ae99817a-8218-4c21-85d7-bcde2583b20f/Analysis-of-the-Iridium-33-Cosmos-2251-Collision.pdf",
    },
    "shepperd": {
        "label": "R. Shepperd (Iridium), Subsequent Assessment of the Collision between Iridium 33 and COSMOS 2251 (AMOS 2023)",
        "url": "https://amostech.com/TechnicalPapers/2023/Conjunction-RPO/Shepperd.pdf",
    },
    "liou": {
        "label": "J.-C. Liou, An Analysis of the FY-1C, Iridium 33, and Cosmos 2251 Fragments (NASA, 2013)",
        "url": "https://ntrs.nasa.gov/citations/20150003820",
    },
    "jspoc": {
        "label": "US Air Force: JFCC Space achieves flight safety milestone (Dec 2009)",
        "url": "https://www.vandenberg.spaceforce.mil/News/Article-Display/Article/339957/jfcc-space-achieves-flight-safety-milestone/",
    },
    "iss_2012": {
        "label": "SpacePolicyOnline: ISS swerves to avoid Iridium debris (31 Oct 2012)",
        "url": "https://spacepolicyonline.com/news/iss-swerves-to-avoid-iridium-debris-readies-for-spacewalk-update",
    },
    "wiki": {
        "label": "Wikipedia: 2009 satellite collision",
        "url": "https://en.wikipedia.org/wiki/2009_satellite_collision",
    },
}

FACTS = [
    {"date": "2009-02-04", "source": "kelso",
     "text": "From 4 February, all 14 reports of the free SOCRATES screening (public TLE data) predicted an "
             "Iridium 33 x Cosmos 2251 approach at the collision time, between 117 m and 1.8 km. None made its Top Ten."},
    {"date": "2009-02-04", "source": "kelso",
     "text": "Iridium 33 had 10 to 15 predicted approaches within 5 km every week. With TLE data, this one could "
             "not be told apart from the rest."},
    {"date": "2009-02-09", "source": "shepperd",
     "text": "Iridium planned a routine station-keeping maneuver for Iridium 33."},
    {"date": "2009-02-10", "source": "shepperd",
     "text": "At 07:10 and 08:00 UTC, two hydrazine burns of 0.0022 m/s raised its orbit by 8.3 m, onto Cosmos "
             "2251's path. Iridium could not see the military's precise catalog; the military did not know about the burn."},
    {"date": "2009-02-10", "source": "kelso",
     "text": "The last SOCRATES report, at 15:02 UTC, predicted a 584 m miss and ranked the approach 152nd."},
    {"date": "2009-02-10", "source": "shepperd",
     "text": "At 16:55:59.8 UTC, Iridium 33 (operational) and Cosmos 2251 (defunct since about 1995) collided at "
             "11.6 km/s over Siberia. Both were destroyed."},
]

AFTERMATH = [
    {"date": "2009-04", "source": "shepperd",
     "text": "Iridium and the US military agreed to share data: Iridium sends planned maneuvers, the military "
             "returns daily screenings with covariance."},
    {"date": "2009-08-05", "source": "kelso",
     "text": "In one week the debris produced 629 predicted approaches within 5 km with Iridium and Orbcomm satellites."},
    {"date": "2009-12-18", "source": "jspoc",
     "text": "US military screening grew from about 120 to about 1,150 active satellites."},
    {"date": "2012-10-31", "source": "iss_2012",
     "text": "The International Space Station changed its orbit to avoid a piece of Iridium 33 debris."},
    {"date": "2013-01", "source": "liou",
     "text": "NASA: 2,201 fragments catalogued from the collision, 1,821 still in orbit."},
    {"date": "2023", "source": "shepperd",
     "text": "Iridium replayed the archived data: merged, it showed the risk days ahead. In its words, "
             "\"no one shared their bucket\"."},
]

# --- Published numbers ----------------------------------------------------------------------------
TCA = datetime(2009, 2, 10, 16, 55, 59, 820_000, tzinfo=timezone.utc)  # Shepperd 2023 (Kelso: 16:55:59.806)
REL_SPEED_KMS = 11.6  # Kelso 2009, Shepperd 2023
ALTITUDE_KM = 789.0  # Wikipedia, "2009 satellite collision" (~789-790 km)
IRIDIUM_INC_DEG, COSMOS_INC_DEG = 86.0, 74.0  # Kelso 2009, Table 1
IRIDIUM_DRY_KG, COSMOS_DRY_KG = 556.0, 900.0  # Kelso 2009, Table 1 (dry mass)
# Hard-body radii used in Iridium's own replay: Iridium 33 3.942 m; Cosmos 2251 16 m (Strela-2M with its
# gravity-gradient boom). Shepperd 2023.
IRIDIUM_HBR_M, COSMOS_HBR_M = 3.942, 16.0
# The station-keeping burns that put Iridium 33 on the collision course (Shepperd 2023, Table 1).
CAUSE_BURNS = [("2009-02-10T07:10:33.195Z", 0.0021685), ("2009-02-10T08:00:47.190Z", 0.0021685)]
# Iridium's replay, Table 2 (Foster 2-D Pc). Shared = Iridium orbit estimate with its constructed covariance
# against the military (JSpOC) catalog; one-sided = JSpOC data alone.
SHARED_PC = [
    ("2009-02-07T20:00:00Z", 2.5e-4, 1.2e-23),
    ("2009-02-08T20:00:00Z", 1.2e-3, 9.5e-27),
    ("2009-02-09T20:00:00Z", 3.3e-2, 2.6e-51),
    ("2009-02-10T15:40:00Z", 7.8e-2, 4.9e-4),
]
CATALOG_COUNTS = [
    ("2009-08-26", 406 + 960, 406 + 960 - 16 - 32, "kelso"),
    ("2013-01", 1603 + 598, 1342 + 479, "liou"),
]
KNOCK_ON_CONJUNCTIONS = 154 + 33 + 334 + 108  # Kelso 2009: 5 Aug 2009, 7 days, within 5 km

# --- Modelling assumptions ------------------------------------------------------------------------
# Planning epoch: 9 Feb 20:00 UTC, the day the station-keeping burn was planned and the time of Iridium's
# replayed screening for that day (Shepperd 2023).
PLANNING_AT = datetime(2009, 2, 9, 20, 0, tzinfo=timezone.utc)
# Iridium's conservative constructed covariance for Iridium 33 (Shepperd 2023): R = 20, T = 120*dt + 60,
# N = 20 metres, dt in days from the orbit estimate to TCA.
_DT_DAYS = (TCA - PLANNING_AT).total_seconds() / 86400.0
IRIDIUM_SIGMA_RTN_M = (20.0, 120.0 * _DT_DAYS + 60.0, 20.0)
# Cosmos 2251's military covariance was not published: same order of magnitude as a 1-2 day old orbit,
# as in the 2021 reconstruction (app.physics.incident). Assumption.
COSMOS_SIGMA_RTN_M = (30.0, 300.0, 50.0)
# Hydrazine monopropellant (Shepperd 2023 confirms hydrazine); Isp not published, typical value assumed.
IRIDIUM_ISP_S = 220.0


def _encounter() -> tuple[Encounter, float]:
    """Circular orbits at the collision altitude, crossing at the published relative speed, as a direct hit."""
    r = EARTH_RADIUS_KM + ALTITUDE_KM
    rel_speed, _, rp, vp, _, vs = min(_crossings(IRIDIUM_INC_DEG, COSMOS_INC_DEG, r, r),
                                      key=lambda it: abs(it[0] - REL_SPEED_KMS))
    x_hat, y_hat = encounter_plane_basis(rp / np.linalg.norm(rp), vs - vp)
    cov2 = _plane_covariance(np.vstack([x_hat, y_hat]), [(rtn_basis(rp, vp), IRIDIUM_SIGMA_RTN_M),
                                                          (rtn_basis(rp, vs), COSMOS_SIGMA_RTN_M)])
    major, minor, angle, _ = _ellipse(cov2)
    enc = Encounter(
        tca=TCA, r_primary_km=rp, v_primary_kms=vp, r_secondary_km=rp, v_secondary_kms=vs,
        sigma_major_m=major, sigma_minor_m=minor, angle_deg=angle,
        hard_body_radius_m=IRIDIUM_HBR_M + COSMOS_HBR_M,
        primary_norad_id=24946, primary_name="IRIDIUM 33", secondary_norad_id=22675, secondary_name="COSMOS 2251",
    )
    return enc, rel_speed


def build() -> CollisionStudy:
    enc, rel_speed = _encounter()
    iridium = Propulsion(IRIDIUM_DRY_KG, IRIDIUM_ISP_S, "Iridium 33: 556 kg dry, hydrazine thrusters")
    plan = plan_maneuvers(enc, now=PLANNING_AT, mover="primary", propulsion=iridium)
    burn = next(o for o in plan.options if o["recommended"])
    cause_dv = sum(dv for _, dv in CAUSE_BURNS)
    fragments = collision_fragment_yield(IRIDIUM_DRY_KG, COSMOS_DRY_KG, REL_SPEED_KMS)
    lead_h = (TCA - datetime.fromisoformat(burn["burnAt"].replace("Z", "+00:00"))).total_seconds() / 3600
    assumptions = [
        "Encounter reconstructed from published values, not from historical element sets: circular orbits at "
        f"{ALTITUDE_KM:g} km (Wikipedia), inclinations {IRIDIUM_INC_DEG:g} and {COSMOS_INC_DEG:g} deg (Kelso, Table 1), "
        f"crossing chosen for the published {REL_SPEED_KMS} km/s relative speed (model: {rel_speed:.2f} km/s).",
        "They collided, so the predicted miss on the planned trajectory is modelled as 0 m (a direct hit).",
        f"Covariance: Iridium 33 uses Iridium's own conservative model, R/T/N = 20 / 120*dt+60 / 20 m (Shepperd), "
        f"{tuple(round(s) for s in IRIDIUM_SIGMA_RTN_M)} m at {_DT_DAYS:.2f} days; Cosmos 2251 {COSMOS_SIGMA_RTN_M} m "
        f"(not published; assumption). Combined in the encounter plane: {enc.sigma_major_m:.0f} x {enc.sigma_minor_m:.0f} m.",
        f"Hard-body radius {enc.hard_body_radius_m:.1f} m: Iridium 33 {IRIDIUM_HBR_M} m + Cosmos 2251 {COSMOS_HBR_M:g} m, "
        "as in Iridium's replay (Shepperd).",
        f"Planning time {PLANNING_AT:%d %b %H:%M} UTC, the day the station-keeping burn was planned (Shepperd). "
        f"Policy as for live events: burn when Pc >= {PC_MANEUVER_THRESHOLD:g}, target Pc <= {PC_TARGET:g} "
        f"and miss >= {MIN_MISS_TARGET_M:g} m (app.physics.maneuver).",
        f"Iridium 33: {IRIDIUM_DRY_KG:g} kg dry mass (Kelso, Table 1; propellant left in 2009 is unknown, so this is "
        f"a lower bound) and hydrazine thrusters (Shepperd) at an assumed Isp of {IRIDIUM_ISP_S:g} s.",
        "The burn is rounded up to the planner's 0.01 m/s grid, so the real minimum may be smaller.",
        f"Debris model: NASA standard breakup model for a catastrophic collision of {IRIDIUM_DRY_KG:g} + "
        f"{COSMOS_DRY_KG:g} kg at {REL_SPEED_KMS} km/s, fragments >= 10 cm (app.physics.cascade).",
        "Pc over time is quoted from Iridium's replay (Shepperd, Table 2, Foster method), not computed here. The "
        "10 Feb one-sided value used knowledge of Iridium's burn to shorten the orbit fit.",
    ]
    return CollisionStudy.model_validate({
        "id": ID,
        "title": "Iridium 33 x Cosmos 2251",
        "date": "2009-02-10",
        "tca": _iso(TCA),
        "relSpeedKms": REL_SPEED_KMS,
        "objects": [
            {"noradId": 24946, "name": "IRIDIUM 33", "cospar": "1997-051C", "status": "operational, hydrazine thrusters",
             "massKg": IRIDIUM_DRY_KG, "maneuverable": True},
            {"noradId": 22675, "name": "COSMOS 2251", "cospar": "1993-036A", "status": "defunct since about 1995",
             "massKg": COSMOS_DRY_KG, "maneuverable": False},
        ],
        "facts": FACTS,
        "aftermath": AFTERMATH,
        "sources": [{"key": key, **value} for key, value in SOURCES.items()],
        "causeBurns": [{"at": at, "dvMs": dv} for at, dv in CAUSE_BURNS],
        "publicWarning": {"reports": 14, "minMissM": 117, "maxMissM": 1812, "finalMissM": 584, "finalRank": 152,
                          "source": "kelso"},
        "pcThreshold": PC_MANEUVER_THRESHOLD,
        "sharedDataPc": [{"at": at, "sharedPc": shared, "oneSidedPc": one} for at, shared, one in SHARED_PC],
        "pcSource": "shepperd",
        "orbitSentinel": {
            "moverNoradId": 24946,
            "planningAt": _iso(PLANNING_AT),
            "pc": float(f"{plan.current_pc:.3g}"),
            "massKg": IRIDIUM_DRY_KG,
            "ispS": IRIDIUM_ISP_S,
            "maneuver": {**burn, "label": f"{burn['dvMs']:.2f} m/s {burn['direction']}, {lead_h:.0f} h before"},
            "causePropellantKg": float(f"{propellant_kg(cause_dv, iridium):.4g}"),
        },
        "debris": {
            "altitudeKm": ALTITUDE_KM,
            "modelFragments": round(fragments),
            "modelMethod": "NASA standard breakup model, fragments >= 10 cm",
            "counts": [{"date": d, "catalogued": c, "inOrbit": o, "source": s} for d, c, o, s in CATALOG_COUNTS],
            "knockOnConjunctionsPerWeek": KNOCK_ON_CONJUNCTIONS,
            "knockOnSource": "kelso",
        },
        "assumptions": assumptions,
    })


_CACHE: list[CollisionStudy] = []


def study() -> CollisionStudy:
    """Deterministic, so it is built once per process."""
    if not _CACHE:
        _CACHE.append(build())
    return _CACHE[0]


def summary() -> dict:
    return {"id": ID, "title": "Iridium 33 x Cosmos 2251", "date": "2009-02-10"}

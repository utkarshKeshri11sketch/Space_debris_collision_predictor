"""Synthetic OMM catalog shaped like frontend/src/api/mockData.ts (same named objects, same shells)."""
import math

import numpy as np

MU = 398600.4418


def _omm(norad_id, name, alt_km, inc, node, anomaly, ecc=0.0004, bstar=1e-4):
    n = math.sqrt(MU / (6378.137 + alt_km) ** 3) * 86400 / (2 * math.pi)
    return {"OBJECT_NAME": name, "NORAD_CAT_ID": norad_id, "EPOCH": "2026-10-30T00:00:00.000Z",
            "MEAN_MOTION": n, "ECCENTRICITY": ecc, "INCLINATION": inc, "RA_OF_ASC_NODE": node,
            "ARG_OF_PERICENTER": 12, "MEAN_ANOMALY": anomaly, "BSTAR": bstar,
            "MEAN_MOTION_DOT": 1e-6, "MEAN_MOTION_DDOT": 0}


def _obj(norad_id, name, kind, alt, inc, node, anomaly, active=None, **kw):
    active = kind == "PAYLOAD" if active is None else active
    return {"noradId": norad_id, "name": name, "type": kind, "active": active, "maneuverable": active,
            "omm": _omm(norad_id, name, alt, inc, node, anomaly, **kw)}


NAMED = [
    _obj(25544, "ISS (ZARYA)", "PAYLOAD", 418, 51.64, 38, 43),
    _obj(50870, "COSMOS 1408 DEB", "DEBRIS", 421, 82.5, 92, 180),
    _obj(59121, "STARLINK-31502", "PAYLOAD", 550, 53.2, 164, 220),
    _obj(48840, "ONEWEB-0461", "PAYLOAD", 1200, 87.9, 90, 30),
    _obj(22285, "SL-16 R/B", "ROCKET_BODY", 840, 71, 143, 70, active=False),
    _obj(30055, "FENGYUN 1C DEB", "DEBRIS", 865, 98.7, 263, 272),
    _obj(33762, "IRIDIUM 33 DEB", "DEBRIS", 780, 86.4, 135, 165),
]


def make_catalog(count=33482, seed=712635):
    rng = np.random.default_rng(seed)
    objects = list(NAMED)
    for index in range(len(objects), count):
        pct = index / count
        kind = "PAYLOAD" if pct < 0.36 else "DEBRIS" if pct < 0.92 else "ROCKET_BODY"
        shell = rng.random()
        alt = (35786 + rng.random() * 80 if shell < 0.025 else 20200 + rng.random() * 120 if shell < 0.065
               else 525 + rng.random() * 80 if shell < 0.57 else 400 + rng.random() * 800)
        inc = rng.random() * 10 if alt > 30000 else 55 + rng.random() * 2 if alt > 2000 else 51.5 + rng.random() * 45
        bstar = {"PAYLOAD": 3e-4, "DEBRIS": 1.5e-3, "ROCKET_BODY": 2e-4}[kind]
        objects.append(_obj(100000 + index, f"OBJ {index}", kind, alt, inc, rng.random() * 360, rng.random() * 360,
                            active=kind == "PAYLOAD" and rng.random() > 0.12, bstar=bstar))
    return objects

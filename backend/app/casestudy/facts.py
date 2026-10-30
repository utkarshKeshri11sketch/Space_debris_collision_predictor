"""Sourced facts for the 2021 China Space Station x Starlink incidents (OWNER: Lead).

Only what public sources state goes here. Anything we have to model (encounter geometry, burn size,
masses at the time) is computed by app/physics/incident.py and labelled as a reconstruction there.
"""
from __future__ import annotations

SOURCES = {
    "un_note": {
        "label": "China, note verbale to the UN Secretary-General, A/AC.105/1262 (3 Dec 2021)",
        "url": "https://www.unoosa.org/oosa/oosadoc/data/documents/2021/aac.105/aac.1051262_0.html",
    },
    "us_reply": {
        "label": "United States, note verbale to the UN, 28 Jan 2022 (reported by SCMP)",
        "url": "https://amp.scmp.com/news/china/diplomacy/article/3166290/spacex-satellites-encounters-chinese-space-station-were-not",
    },
    "email_no_reply": {
        "label": "Chinese foreign ministry: emails to the US received no reply (reported by Dawn/AFP)",
        "url": "https://www.dawn.com/news/1666419",
    },
    "space_com": {
        "label": "Space.com: Tianhe dodged Starlink satellites twice in 2021",
        "url": "https://www.space.com/china-tianhe-space-station-maneuvers-spacex-starlink",
    },
}

CSS = {"noradId": 48274, "name": "CSS (TIANHE)", "cospar": "2021-035A",
       "orbit": "near-circular, ~390 km, inclination ~41.5 deg (UN note)"}

CASES = [
    {
        "id": "case-2021-07-01-css-starlink-1095",
        "title": "China Space Station x Starlink-1095",
        "date": "2021-07-01",
        "station": CSS,
        "starlink": {"noradId": 44971, "name": "STARLINK-1095", "cospar": "2020-001BK"},
        "facts": [
            {"text": "Starlink-1095 maneuvered continuously between 16 May and 24 June 2021 down to an orbit of about 382 km, then stayed there.", "source": "un_note"},
            {"text": "On 1 July 2021 it had a close encounter with the China Space Station, which flew a preventive collision-avoidance maneuver.", "source": "un_note"},
            {"text": "Crew were aboard the station.", "source": "space_com"},
        ],
    },
    {
        "id": "case-2021-10-21-css-starlink-2305",
        "title": "China Space Station x Starlink-2305",
        "date": "2021-10-21",
        "station": CSS,
        "starlink": {"noradId": 47989, "name": "STARLINK-2305", "cospar": "2021-024N"},
        "facts": [
            {"text": "On 21 October 2021 Starlink-2305 had a close encounter with the China Space Station.", "source": "un_note"},
            {"text": "The satellite was maneuvering continuously, its strategy was unknown and its orbital errors were hard to assess, so the station flew another avoidance maneuver.", "source": "un_note"},
            {"text": "Crew were aboard the station.", "source": "space_com"},
        ],
    },
]

AFTERMATH = [
    {"date": "2021-12-03", "text": "China notified the UN Secretary-General under Article V of the Outer Space Treaty (A/AC.105/1262).", "source": "un_note"},
    {"date": "2021-12-28", "text": "China's foreign ministry said its emails to the US about the encounters got no reply.", "source": "email_no_reply"},
    {"date": "2022-01-28", "text": "The US told the UN that US Space Command did not estimate a significant collision probability and the events did not meet emergency notification criteria.", "source": "us_reply"},
]


def case(case_id: str) -> dict | None:
    return next((c for c in CASES if c["id"] == case_id), None)

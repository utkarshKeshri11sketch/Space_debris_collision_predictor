"""Pydantic models mirroring frontend/src/api/types.ts EXACTLY (camelCase field names on purpose).

This file is the API contract. Only the Lead edits it; request changes in docs/CONTRACT_REQUESTS.md.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field

ObjectType = Literal["PAYLOAD", "DEBRIS", "ROCKET_BODY", "UNKNOWN"]
Risk = Literal["critical", "high", "watch"]
Direction = Literal["prograde", "retrograde", "radial", "normal", "none"]
OmmValue = Union[str, int, float]


class CatalogObject(BaseModel):
    noradId: int
    name: str
    type: ObjectType
    active: bool
    maneuverable: bool
    omm: dict[str, OmmValue]


class ObjectRef(BaseModel):
    noradId: int
    name: str
    type: ObjectType
    maneuverable: bool


class Rtn(BaseModel):
    r: float
    t: float
    n: float


class Conjunction(BaseModel):
    id: str
    primary: ObjectRef
    secondary: ObjectRef
    tca: str  # ISO-8601 UTC
    missDistanceM: float
    rtnM: Rtn
    relSpeedKms: float
    pc: float
    risk: Risk


class ManeuverOption(BaseModel):
    id: str
    label: str
    direction: Direction
    dvMs: float
    burnAt: str | None
    newMissM: float
    newPc: float
    propellantKg: float
    recommended: bool


class RangePoint(BaseModel):
    tSec: float
    rangeKm: float


class Covariance(BaseModel):
    sigmaMajorM: float
    sigmaMinorM: float
    angleDeg: float


class ConjunctionDetail(Conjunction):
    rangeSeries: list[RangePoint]
    afterSeries: list[RangePoint] | None = None
    covariance: Covariance
    hardBodyRadiusM: float
    options: list[ManeuverOption]
    brief: str


# ---- Negotiation SSE events (discriminated on "type") ----
class MessageEvent(BaseModel):
    type: Literal["message"] = "message"
    speaker: Literal["mediator", "agentA", "agentB"]
    round: int
    text: str


class ScoreCriterion(BaseModel):
    name: str
    weight: float
    a: float
    b: float


class ScoresEvent(BaseModel):
    type: Literal["scores"] = "scores"
    criteria: list[ScoreCriterion]


class AgreementEvent(BaseModel):
    type: Literal["agreement"] = "agreement"
    mover: ObjectRef
    maneuver: ManeuverOption
    signedBy: list[str]


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    message: str


NegotiationEvent = Annotated[
    Union[MessageEvent, ScoresEvent, AgreementEvent, ErrorEvent], Field(discriminator="type")
]


class NegotiationStart(BaseModel):
    conjunctionId: str


class NegotiationStarted(BaseModel):
    negotiationId: str


# ---- Cascade ----
class CascadeParent(ObjectRef):
    omm: dict[str, OmmValue]


class SpreadDv(BaseModel):
    mean: float
    sd: float


class CascadeYear(BaseModel):
    year: int
    trackedTotal: float
    baselineTotal: float
    extraConjunctionsPct: float
    satellitesAtRisk: float


class SecondaryCollision(BaseModel):
    year: float
    latDeg: float
    lonDeg: float
    altKm: float
    fragments: float


class CascadeResult(BaseModel):
    parent: CascadeParent
    fragmentCount: int
    spreadDvMs: SpreadDv
    seed: int
    years: list[CascadeYear]
    secondaryCollisions: list[SecondaryCollision]


class CascadeRequest(BaseModel):
    noradId: int
    event: Literal["collision", "explosion"]
    years: int
    includeLaunches: bool


class CatalogMeta(BaseModel):
    objectCount: int
    byType: dict[ObjectType, int]
    syncedAt: str
    source: str


# ---- Ask Sentinel ----
class AskRequest(BaseModel):
    question: str


class AskToken(BaseModel):
    """One SSE data payload of /api/ask: {"type":"token","text":"..."}."""
    type: Literal["token"] = "token"
    text: str


# ---- Case studies (past incidents replayed through OrbitSentinel). Not used by the frontend yet;
# see docs/case_studies/CONTRACT.md. ----
class SourcedFact(BaseModel):
    text: str
    source: str  # key into CaseStudy.sources


class DatedFact(SourcedFact):
    date: str


class Source(BaseModel):
    key: str
    label: str
    url: str


class IncidentReality(BaseModel):
    """What happened: the station moved. Burn size is not public, so it is reconstructed."""
    moverNoradId: int
    dvMs: float | None
    propellantKg: float
    massKg: float
    ispS: float
    basis: str  # how dvMs/propellantKg were obtained (reconstruction method)


class Criterion(BaseModel):
    name: str
    weight: float
    a: float
    b: float


class IncidentDecision(BaseModel):
    """What OrbitSentinel's mediator recommends."""
    moverSide: Literal["a", "b"]
    moverNoradId: int
    maneuver: ManeuverOption
    criteria: list[Criterion]


class IncidentNarrative(BaseModel):
    reality: str
    orbitSentinel: str
    brief: str


class IncidentComparison(BaseModel):
    propellantSavedKg: float
    propellantRatio: float
    dvRealityMs: float | None
    dvOrbitSentinelMs: float | None


class CaseStudyStatus(BaseModel):
    physics: Literal["ready", "pending", "error"]
    ai: Literal["ready", "pending", "error"]


class CaseStudy(BaseModel):
    id: str
    title: str
    date: str
    facts: list[SourcedFact]
    aftermath: list[DatedFact]
    sources: list[Source]
    conjunction: ConjunctionDetail | None
    reality: IncidentReality | None
    orbitSentinel: IncidentDecision | None
    narrative: IncidentNarrative | None
    comparison: IncidentComparison | None
    assumptions: list[str]
    status: CaseStudyStatus

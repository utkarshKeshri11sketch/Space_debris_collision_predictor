export type ObjectType = 'PAYLOAD' | 'DEBRIS' | 'ROCKET_BODY' | 'UNKNOWN';
export type Risk = 'critical' | 'high' | 'watch';
export interface CatalogObject {
  noradId: number;
  name: string;
  type: ObjectType;
  active: boolean;
  maneuverable: boolean;
  omm: Record<string, string | number>;
}
export interface ObjectRef {
  noradId: number;
  name: string;
  type: ObjectType;
  maneuverable: boolean;
}
export interface Conjunction {
  id: string;
  primary: ObjectRef;
  secondary: ObjectRef;
  tca: string;
  missDistanceM: number;
  rtnM: { r: number; t: number; n: number };
  relSpeedKms: number;
  pc: number;
  risk: Risk;
}
export interface ManeuverOption {
  id: string;
  label: string;
  direction: 'prograde' | 'retrograde' | 'radial' | 'normal' | 'none';
  dvMs: number;
  burnAt: string | null;
  newMissM: number;
  newPc: number;
  propellantKg: number;
  recommended: boolean;
}
export interface ConjunctionDetail extends Conjunction {
  rangeSeries: { tSec: number; rangeKm: number }[];
  afterSeries?: { tSec: number; rangeKm: number }[];
  covariance: { sigmaMajorM: number; sigmaMinorM: number; angleDeg: number };
  hardBodyRadiusM: number;
  options: ManeuverOption[];
  brief: string;
}
export type NegotiationEvent =
  | { type: 'message'; speaker: 'mediator' | 'agentA' | 'agentB'; round: number; text: string }
  | { type: 'scores'; criteria: { name: string; weight: number; a: number; b: number }[] }
  | { type: 'agreement'; mover: ObjectRef; maneuver: ManeuverOption; signedBy: string[] }
  | { type: 'error'; message: string };
export interface CascadeResult {
  parent: ObjectRef & { omm: Record<string, string | number> };
  fragmentCount: number;
  spreadDvMs: { mean: number; sd: number };
  seed: number;
  years: {
    year: number;
    trackedTotal: number;
    baselineTotal: number;
    extraConjunctionsPct: number;
    satellitesAtRisk: number;
  }[];
  secondaryCollisions: {
    year: number;
    latDeg: number;
    lonDeg: number;
    altKm: number;
    fragments: number;
  }[];
}
export interface CascadeRequest {
  noradId: number;
  event: 'collision' | 'explosion';
  years: number;
  includeLaunches: boolean;
}
export interface CatalogMeta {
  objectCount: number;
  byType: Record<ObjectType, number>;
  syncedAt: string;
  source: string;
}
export interface SourcedFact {
  text: string;
  source: string;
}
export interface CaseStudySummary {
  id: string;
  title: string;
  date: string;
}
export interface CaseStudy extends CaseStudySummary {
  facts: SourcedFact[];
  aftermath: (SourcedFact & { date: string })[];
  sources: { key: string; label: string; url: string }[];
  conjunction: ConjunctionDetail | null;
  reality: {
    moverNoradId: number;
    dvMs: number | null;
    propellantKg: number;
    massKg: number;
    ispS: number;
    basis: string;
  } | null;
  orbitSentinel: {
    moverSide: 'a' | 'b';
    moverNoradId: number;
    moverMassKg: number;
    maneuver: ManeuverOption;
    criteria: { name: string; weight: number; a: number; b: number }[];
    alternative: ManeuverOption | null;
  } | null;
  narrative: { reality: string; orbitSentinel: string; brief: string } | null;
  comparison: {
    propellantSavedKg: number;
    propellantRatio: number;
    dvRealityMs: number | null;
    dvOrbitSentinelMs: number | null;
  } | null;
  assumptions: string[];
  status: { physics: 'ready' | 'pending' | 'error'; ai: 'ready' | 'pending' | 'error' };
}
/** Cascade Lab "Rewind 2009": a real collision, what avoiding it cost, and what the debris cost. */
export interface CollisionStudy extends CaseStudySummary {
  tca: string;
  relSpeedKms: number;
  objects: {
    noradId: number;
    name: string;
    cospar: string;
    status: string;
    massKg: number;
    maneuverable: boolean;
  }[];
  facts: (SourcedFact & { date: string })[];
  aftermath: (SourcedFact & { date: string })[];
  sources: { key: string; label: string; url: string }[];
  causeBurns: { at: string; dvMs: number }[];
  publicWarning: {
    reports: number;
    minMissM: number;
    maxMissM: number;
    finalMissM: number;
    finalRank: number;
    source: string;
  };
  pcThreshold: number;
  sharedDataPc: { at: string; sharedPc: number; oneSidedPc: number }[];
  pcSource: string;
  orbitSentinel: {
    moverNoradId: number;
    planningAt: string;
    pc: number;
    massKg: number;
    ispS: number;
    maneuver: ManeuverOption;
    causePropellantKg: number;
  };
  debris: {
    altitudeKm: number;
    modelFragments: number;
    modelMethod: string;
    counts: { date: string; catalogued: number; inOrbit: number | null; source: string }[];
    knockOnConjunctionsPerWeek: number;
    knockOnSource: string;
  };
  assumptions: string[];
}

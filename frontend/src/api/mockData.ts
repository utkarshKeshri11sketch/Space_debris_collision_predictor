import type { CatalogObject, CascadeRequest, CascadeResult, CatalogMeta, ConjunctionDetail, ManeuverOption, NegotiationEvent, ObjectRef, ObjectType } from './types';
import { seededRandom } from '../lib/random';
export const DEMO_EPOCH_MS = Date.now();
export const OBJECT_COUNT = 33482;
const iso = (hours: number) => new Date(DEMO_EPOCH_MS + hours * 3600000).toISOString();
function omm(noradId: number, name: string, altitudeKm: number, inclination: number, node: number, anomaly: number): CatalogObject['omm'] {
  const meanMotion = Math.sqrt(398600.4418 / Math.pow(6378.137 + altitudeKm, 3)) * 86400 / (2 * Math.PI);
  return {
    OBJECT_NAME: name, NORAD_CAT_ID: noradId, EPOCH: new Date(DEMO_EPOCH_MS).toISOString(),
    MEAN_MOTION: meanMotion, ECCENTRICITY: 0.0004, INCLINATION: inclination,
    RA_OF_ASC_NODE: node, ARG_OF_PERICENTER: 12, MEAN_ANOMALY: anomaly,
    BSTAR: 0.00001, MEAN_MOTION_DOT: 0.000001, MEAN_MOTION_DDOT: 0,
  };
}
function named(noradId: number, name: string, type: ObjectType, altitude: number, inclination: number, node: number, anomaly: number, active = type === 'PAYLOAD'): CatalogObject {
  return { noradId, name, type, active, maneuverable: active, omm: omm(noradId, name, altitude, inclination, node, anomaly) };
}
export const namedObjects = [
  named(25544, 'ISS (ZARYA)', 'PAYLOAD', 418, 51.64, 38, 43),
  named(50870, 'COSMOS 1408 DEB', 'DEBRIS', 421, 82.5, 92, 180),
  named(59121, 'STARLINK-31502', 'PAYLOAD', 550, 53.2, 164, 220),
  named(48840, 'ONEWEB-0461', 'PAYLOAD', 1200, 87.9, 90, 30),
  named(44804, 'CARTOSAT-3', 'PAYLOAD', 509, 97.5, 221, 50),
  named(22285, 'SL-16 R/B', 'ROCKET_BODY', 840, 71, 143, 70, false),
  named(54361, 'OCEANSAT-3', 'PAYLOAD', 742, 98.3, 258, 270),
  named(30055, 'FENGYUN 1C DEB', 'DEBRIS', 865, 98.7, 263, 272),
  named(43013, 'NOAA 20', 'PAYLOAD', 824, 98.7, 130, 165),
  named(33762, 'IRIDIUM 33 DEB', 'DEBRIS', 780, 86.4, 135, 165),
] satisfies CatalogObject[];
let catalogCache: CatalogObject[] | undefined;
/** Deterministic catalog; each record goes through the same native OMM SGP4 path as live data. */
export function getMockCatalog(): CatalogObject[] {
  if (catalogCache) return catalogCache;
  const random = seededRandom(712635);
  const objects: CatalogObject[] = [...namedObjects];
  for (let index = objects.length; index < OBJECT_COUNT; index++) {
    const percentile = index / OBJECT_COUNT;
    const type: ObjectType = percentile < 0.36 ? 'PAYLOAD' : percentile < 0.92 ? 'DEBRIS' : 'ROCKET_BODY';
    const shell = random();
    const altitude = shell < 0.025 ? 35786 + random() * 80 : shell < 0.065 ? 20200 + random() * 120 : shell < 0.57 ? 525 + random() * 80 : 400 + random() * 800;
    const inclination = altitude > 30000 ? random() * 10 : altitude > 2000 ? 55 + random() * 2 : random() < 0.28 ? 97.3 + random() * 1.8 : random() < 0.65 ? 51.5 + random() * 3 : 60 + random() * 35;
    const noradId = 100000 + index;
    const active = type === 'PAYLOAD' && random() > 0.12;
    const name = type === 'PAYLOAD' ? `ORBITNET-${String(index).padStart(5, '0')}` : type === 'DEBRIS' ? `CATALOG DEB ${noradId}` : `UPPER STAGE ${noradId}`;
    objects.push({ noradId, name, type, active, maneuverable: active, omm: omm(noradId, name, altitude, inclination, random() * 360, random() * 360) });
  }
  catalogCache = objects;
  return objects;
}
export function getMockMeta(): CatalogMeta {
  const byType: CatalogMeta['byType'] = { PAYLOAD: 0, DEBRIS: 0, ROCKET_BODY: 0, UNKNOWN: 0 };
  for (const object of getMockCatalog()) byType[object.type]++;
  return { objectCount: OBJECT_COUNT, byType, syncedAt: new Date(DEMO_EPOCH_MS).toISOString(), source: 'Synthetic OMM catalog · sample data' };
}
const ref = (index: number): ObjectRef => {
  const { noradId, name, type, maneuverable } = namedObjects[index];
  return { noradId, name, type, maneuverable };
};
function options(tcaHours: number, miss: number, pc: number): ManeuverOption[] {
  return [
    { id: 'option-a', label: 'A', direction: 'prograde', dvMs: 0.42, burnAt: iso(tcaHours - 6), newMissM: 4200, newPc: 2.3e-8, propellantKg: 0.18, recommended: true },
    { id: 'option-b', label: 'B', direction: 'normal', dvMs: 0.67, burnAt: iso(tcaHours - 4), newMissM: 6800, newPc: 8.1e-10, propellantKg: 0.29, recommended: false },
    { id: 'no-action', label: 'No action', direction: 'none', dvMs: 0, burnAt: null, newMissM: miss, newPc: pc, propellantKg: 0, recommended: false },
  ];
}
function detail(id: string, a: number, b: number, hours: number, missDistanceM: number, pc: number, relSpeedKms: number, risk: ConjunctionDetail['risk'], brief: string): ConjunctionDetail {
  const rangeSeries = Array.from({ length: 81 }, (_, i) => {
    const tSec = (i - 40) * 1.5;
    return { tSec, rangeKm: Math.hypot(missDistanceM / 1000, tSec * relSpeedKms) };
  });
  return {
    id, primary: ref(a), secondary: ref(b), tca: iso(hours), missDistanceM,
    rtnM: { r: Math.round(missDistanceM * 0.31), t: Math.round(missDistanceM * 0.91), n: Math.round(missDistanceM * 0.273) },
    relSpeedKms, pc, risk, rangeSeries,
    afterSeries: rangeSeries.map(({ tSec }) => ({ tSec, rangeKm: Math.hypot(4.2, tSec * relSpeedKms) })),
    covariance: { sigmaMajorM: 186, sigmaMinorM: 74, angleDeg: 32 },
    hardBodyRadiusM: a === 0 ? 58 : 8, options: options(hours, missDistanceM, pc), brief,
  };
}
export const mockConjunctions: ConjunctionDetail[] = [
  detail('iss-cosmos', 0, 1, 18.03, 412, 3.1e-4, 14.2, 'critical', 'A COSMOS 1408 fragment is projected to pass 412 m from the ISS. The fragment cannot maneuver. A 0.42 m/s prograde burn six hours before closest approach raises modeled separation to 4.2 km. This sample recommendation requires an operator decision.'),
  detail('starlink-oneweb', 2, 3, 31.4, 690, 8.7e-5, 12.8, 'high', 'Both spacecraft are maneuverable. Compare propellant cost, mission disruption and operator readiness before deciding who moves. The sample negotiation favors STARLINK-31502 for the smaller mission impact.'),
  detail('cartosat-fengyun', 4, 7, 47.2, 1250, 7.2e-6, 10.4, 'watch', 'A stable watch-level event. Continue covariance updates; the current screening does not recommend a maneuver.'),
  detail('oceansat-iridium', 6, 9, 63.8, 1800, 4.5e-6, 11.2, 'watch', 'The miss distance remains above the sample alert envelope. The debris object cannot maneuver.'),
  detail('noaa-rocket', 8, 5, 85.5, 2340, 3.2e-6, 9.8, 'watch', 'An upper stage crosses the NOAA 20 orbital plane. Monitor with the next catalog refresh.'),
  detail('oneweb-fengyun', 3, 7, 112.7, 2870, 2.1e-6, 8.7, 'watch', 'No avoidance action is proposed at this screening epoch. The sample covariance remains within normal bounds.'),
  detail('iss-iridium', 0, 9, 146.3, 3620, 1.4e-6, 13.1, 'watch', 'Long-horizon watch event. Re-screen as the epoch approaches before making any operational decision.'),
];
export const sentinelBrief = 'One critical conjunction needs review. ISS and a COSMOS 1408 fragment approach within 412 m in 18 hours. An avoidance burn raises modeled separation to 4.2 km. A second event is ready for operator negotiation. All values shown are sample data.';
export function negotiationEvents(conjunctionId: string): NegotiationEvent[] {
  const event = mockConjunctions.find((item) => item.id === conjunctionId) ?? mockConjunctions[1];
  return [
    { type: 'message', speaker: 'mediator', round: 0, text: `Screening confirms a ${event.missDistanceM} m approach. Both operators can maneuver. Please submit a minimal-cost avoidance proposal.` },
    { type: 'message', speaker: 'agentA', round: 1, text: 'STARLINK-31502 can execute a 0.42 m/s prograde burn. Estimated propellant: 0.18 kg. Our next station-keeping window already covers the required uplink.' },
    { type: 'message', speaker: 'agentB', round: 1, text: 'ONEWEB-0461 can execute a 0.67 m/s normal burn, using 0.29 kg. That interrupts a scheduled coverage window. We support the lower-cost STARLINK maneuver if separation exceeds 4 km.' },
    { type: 'message', speaker: 'mediator', round: 2, text: 'Independent propagation gives 4.2 km separation and Pc 2.3 × 10⁻⁸ for proposal A. Evaluating fuel efficiency, mission continuity, readiness and risk reduction.' },
    { type: 'scores', criteria: [
      { name: 'Fuel efficiency', weight: 0.3, a: 92, b: 68 },
      { name: 'Mission continuity', weight: 0.3, a: 94, b: 62 },
      { name: 'Operator readiness', weight: 0.2, a: 96, b: 85 },
      { name: 'Risk reduction', weight: 0.2, a: 97, b: 99 },
    ] },
    { type: 'message', speaker: 'agentA', round: 3, text: 'Proposal A accepted. Burn: 0.42 m/s prograde; modeled separation: 4.2 km. Submitted for human review and flight approval.' },
    { type: 'message', speaker: 'agentB', round: 3, text: 'Agreed. ONEWEB-0461 maintains its current trajectory. We will continue tracking through closest approach and verify the updated state vector.' },
    { type: 'agreement', mover: event.primary, maneuver: event.options[0], signedBy: ['STARLINK operator agent', 'ONEWEB operator agent', 'Sentinel mediator'] },
  ];
}
export function getMockCascade(request: CascadeRequest): CascadeResult {
  const parent = getMockCatalog().find((object) => object.noradId === request.noradId);
  if (!parent) throw new Error('Object is not in the loaded catalog');
  const years = Math.max(1, Math.min(25, Math.round(request.years)));
  const fragmentCount = request.event === 'collision' ? 12784 : 4260;
  const multiplier = request.event === 'collision' ? 1 : 0.4;
  const secondaryCollisions = [
    { year: 8.4, latDeg: 36.8, lonDeg: 74.2, altKm: 825, fragments: Math.round(3840 * multiplier) },
    { year: 17.2, latDeg: -20.4, lonDeg: -110.5, altKm: 910, fragments: Math.round(5720 * multiplier) },
  ].filter((item) => item.year <= years);
  return {
    parent: { noradId: parent.noradId, name: parent.name, type: parent.type, maneuverable: parent.maneuverable, omm: parent.omm },
    fragmentCount, spreadDvMs: { mean: request.event === 'collision' ? 85 : 32, sd: request.event === 'collision' ? 38 : 15 }, seed: 90421 + request.noradId,
    years: Array.from({ length: years + 1 }, (_, year) => {
      const baselineTotal = OBJECT_COUNT + (request.includeLaunches ? year * 1250 : -year * 42);
      const secondaryFragments = secondaryCollisions.filter((collision) => collision.year <= year).reduce((sum, collision) => sum + collision.fragments, 0);
      return {
        year, baselineTotal,
        trackedTotal: Math.round(baselineTotal + fragmentCount * Math.exp(-year / 57) + secondaryFragments),
        extraConjunctionsPct: Math.round((19 + year * 2.8 + secondaryFragments / 210) * multiplier * 10) / 10,
        satellitesAtRisk: Math.round((680 + year * 74 + secondaryFragments * 0.045) * multiplier),
      };
    }), secondaryCollisions,
  };
}

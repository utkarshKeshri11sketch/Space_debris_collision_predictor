import type { CascadeResult, CatalogObject } from '../../api/types';

// Earth-impact and preparedness model for the Cascade Lab.
// Everything here is derived on the client from an existing CascadeResult, so the API contract is
// unchanged. Every constant below is an assumption taken from a cited source; the model is an
// order-of-magnitude teaching aid, not an operational forecast.

const MU_KM3_S2 = 398600.4418;
const EARTH_RADIUS_KM = 6378.137;

export function meanAltitudeKm(omm: Record<string, string | number>): number {
  const meanMotionRadS = (Number(omm.MEAN_MOTION) * 2 * Math.PI) / 86400;
  if (!Number.isFinite(meanMotionRadS) || meanMotionRadS <= 0) return NaN;
  return Math.cbrt(MU_KM3_S2 / meanMotionRadS ** 2) - EARTH_RADIUS_KM;
}

// Fragment lifetime τ(h) = τ_ref · exp((h − h_ref) / H), calibrated on two real fragment clouds:
// - Cosmos 1408 (~480 km, Nov 2021): 1,122 of 1,783 tracked fragments had decayed by Aug 2022, about
//   9 months later (SpaceNews, 2022) → τ = 0.75 / −ln(661 / 1783) ≈ 0.76 years.
// - Fengyun-1C (~865 km, Jan 2007): NASA projects about half of the fragments still in orbit in 2033,
//   26 years after the breakup (Liou, NASA NTRS 20150003820) → τ = 26 / ln 2 ≈ 37.5 years. The same
//   report counts 3,076 of 3,378 still in orbit after 6 years (τ ≈ 64 years if fitted on that); the
//   projection is used because it spans the decades the Lab shows. Check: the same fit keeps 80% of
//   Iridium 33 / Cosmos 2251 fragments (789 km) after 4 years, against 1,821 of 2,201 (83%) in NASA's count.
// Fragments have a high area-to-mass ratio, so they decay faster than intact spacecraft, which ESA
// puts at ~100–150 years from 800 km. Solar-cycle and thermosphere changes are ignored here.
const LOW_ANCHOR = { altKm: 480, tauYears: 0.75 / -Math.log(661 / 1783) };
const HIGH_ANCHOR = { altKm: 865, tauYears: 26 / Math.LN2 };
const SCALE_HEIGHT_KM =
  (HIGH_ANCHOR.altKm - LOW_ANCHOR.altKm) / Math.log(HIGH_ANCHOR.tauYears / LOW_ANCHOR.tauYears);

export function fragmentLifetimeYears(altKm: number): number {
  return HIGH_ANCHOR.tauYears * Math.exp((altKm - HIGH_ANCHOR.altKm) / SCALE_HEIGHT_KM);
}

export function remainingFraction(altKm: number, yearsSinceBreakup: number): number {
  if (yearsSinceBreakup <= 0) return 1;
  return Math.exp(-yearsSinceBreakup / fragmentLifetimeYears(altKm));
}

export function yearsToClear(altKm: number, fraction = 0.9): number {
  return fragmentLifetimeYears(altKm) * -Math.log(1 - fraction);
}

export type Persistence = 'years' | 'decades' | 'centuries';
export function persistenceClass(altKm: number): Persistence {
  const clear = yearsToClear(altKm);
  return clear < 10 ? 'years' : clear < 100 ? 'decades' : 'centuries';
}

// Fengyun-1C fragments formed a full shell around Earth ~7–8 months after the breakup
// (Pardini & Anselmo). Used as the reference ring-formation time; it varies with orbit.
export const RING_FORMATION_MONTHS = { min: 7, max: 8 } as const;

// Services commonly operated in each LEO band, from public orbit data of named missions.
const SERVICE_BANDS = [
  { minKm: 400, maxKm: 440, service: 'Crewed stations', examples: 'ISS ~420 km' },
  { minKm: 470, maxKm: 570, service: 'Satellite broadband', examples: 'Starlink 480–550 km' },
  {
    minKm: 690,
    maxKm: 830,
    service: 'Weather and Earth observation',
    examples: 'Landsat 705 km, MetOp 817 km, JPSS 824 km',
  },
  { minKm: 760, maxKm: 800, service: 'Mobile satellite phones', examples: 'Iridium 781 km' },
  { minKm: 1150, maxKm: 1250, service: 'Satellite broadband', examples: 'OneWeb ~1,200 km' },
] as const;
// A fresh fragment cloud spreads in altitude; treat services within this margin as exposed.
const BAND_MARGIN_KM = 75;

export function servicesNear(altKm: number) {
  return SERVICE_BANDS.filter(
    (band) => altKm >= band.minKm - BAND_MARGIN_KM && altKm <= band.maxKm + BAND_MARGIN_KM,
  );
}

export interface EarthImpact {
  parentAltKm: number;
  lifetimeYears: number;
  yearsToClear90: number;
  persistence: Persistence;
  reentered: number;
  inOrbit: number;
  remainingAfter100Years: number;
  reentriesPerYear: number;
  satellitesPossiblyLost: number;
  services: ReturnType<typeof servicesNear>;
  reenteredMassKg: number;
  reentryMassKgPerYear: number;
  aluminaKg: number;
}

// Breakup mass. OMM carries no mass, so these mirror the cascade simulator's own assumptions
// (backend/app/physics/cascade.py: _MASS_BY_NORAD, _MASS_BY_TYPE, INTACT_TARGET_KG). A debris parent
// is assumed to break up by striking an 800 kg satellite, and so is every secondary collision.
const MASS_BY_NORAD_KG: Record<number, number> = { 22285: 8900, 25544: 420000 };
const MASS_BY_TYPE_KG: Record<CascadeResult['parent']['type'], number> = {
  PAYLOAD: 800,
  ROCKET_BODY: 1400,
  DEBRIS: 1,
  UNKNOWN: 100,
};
const STRUCK_SATELLITE_KG = 800;

export function breakupMassKg(parent: CascadeResult['parent']): number {
  const mass = MASS_BY_NORAD_KG[parent.noradId] ?? MASS_BY_TYPE_KG[parent.type];
  return parent.type === 'DEBRIS' ? mass + STRUCK_SATELLITE_KG : mass;
}

// Aluminium oxide formed on reentry. Ferreira et al. (GRL 2024): a 250 kg satellite that is ~30%
// aluminium makes ~30 kg of Al2O3, i.e. 0.12 kg per kg reentered. Applied to all fragments as a model
// estimate; rocket stages carry more aluminium, so this likely underestimates them.
const ALUMINA_PER_KG = 30 / 250;
// Context from the same paper: all reentries in 2022 made ~17 t; planned mega-constellations ~360 t/yr.
export const ALUMINA_2022_KG = 17_000;
export const ALUMINA_MEGACONSTELLATION_KG_PER_YEAR = 360_000;

// Each fragment source (the breakup at year 0, then every secondary collision at its own altitude)
// decays independently from the moment it happens. Mass is spread evenly over a source's fragments.
function sources(result: CascadeResult, parentAltKm: number, year: number) {
  return [
    {
      year: 0,
      altKm: parentAltKm,
      fragments: result.fragmentCount,
      massKg: breakupMassKg(result.parent),
    },
    ...result.secondaryCollisions
      .filter((collision) => collision.year <= year)
      .map((collision) => ({ ...collision, massKg: STRUCK_SATELLITE_KG })),
  ];
}

export function earthImpact(result: CascadeResult, year: number): EarthImpact {
  const parentAltKm = meanAltitudeKm(result.parent.omm);
  const active = sources(result, parentAltKm, year);
  const inOrbitAt = (t: number) =>
    active.reduce(
      (sum, source) => sum + source.fragments * remainingFraction(source.altKm, t - source.year),
      0,
    );
  const created = active.reduce((sum, source) => sum + source.fragments, 0);
  const inOrbit = inOrbitAt(year);
  const lifetimeYears = fragmentLifetimeYears(parentAltKm);
  const reenteredMassKg = active.reduce(
    (sum, source) =>
      sum + source.massKg * (1 - remainingFraction(source.altKm, year - source.year)),
    0,
  );
  return {
    parentAltKm,
    lifetimeYears,
    yearsToClear90: yearsToClear(parentAltKm),
    persistence: persistenceClass(parentAltKm),
    reentered: Math.round(created - inOrbit),
    inOrbit: Math.round(inOrbit),
    remainingAfter100Years: remainingFraction(parentAltKm, 100),
    // Instantaneous decay rate dN/dt = Σ N_i / τ_i, as fragments per year.
    reentriesPerYear: Math.round(
      active.reduce(
        (sum, source) =>
          sum +
          (source.fragments * remainingFraction(source.altKm, year - source.year)) /
            fragmentLifetimeYears(source.altKm),
        0,
      ),
    ),
    // Each secondary collision destroys at least one object; if it was a working satellite it
    // needs a replacement launch. This is an upper bound on satellites lost, not a count.
    satellitesPossiblyLost: active.length - 1,
    services: servicesNear(parentAltKm),
    reenteredMassKg,
    reentryMassKgPerYear: active.reduce(
      (sum, source) =>
        sum +
        (source.massKg * remainingFraction(source.altKm, year - source.year)) /
          fragmentLifetimeYears(source.altKm),
      0,
    ),
    aluminaKg: reenteredMassKg * ALUMINA_PER_KG,
  };
}

// Weather, climate and Earth-observation missions, matched by catalog name prefix (CelesTrak names).
const CLIMATE_MISSION =
  /^(NOAA|METOP|SUOMI NPP|NPP|JPSS|LANDSAT|SENTINEL|FENGYUN 3|FY-3|TERRA|AQUA|AURA|DMSP|METEOR-M|GCOM|OCO|CRYOSAT|SMOS|SWOT|SARAL|GOSAT|OCEANSAT|EARTHCARE|SMAP|ICESAT|GRACE)\b/i;

export interface BandSatellite {
  noradId: number;
  name: string;
  altKm: number;
}

/**
 * The bundled archive snapshot has no active roster, so every object reads inactive. Counts of active
 * satellites, and the cascade's at-risk and extra-approach figures (weighted by active payloads), are
 * then unknown rather than zero.
 */
export function activityKnown(catalog: CatalogObject[] | undefined): boolean {
  return Boolean(catalog?.some((object) => object.active));
}
export const ACTIVITY_UNKNOWN =
  'This catalog does not record which satellites are active, so they cannot be counted. Refresh to the live CelesTrak catalog for these figures.';

/** Real active payloads from the loaded catalog within the cloud's altitude band. */
export function satellitesInBand(catalog: CatalogObject[], altKm: number) {
  const inBand: BandSatellite[] = [];
  for (const object of catalog) {
    if (object.type !== 'PAYLOAD' || !object.active) continue;
    const objectAlt = meanAltitudeKm(object.omm);
    if (Math.abs(objectAlt - altKm) <= BAND_MARGIN_KM)
      inBand.push({ noradId: object.noradId, name: object.name, altKm: objectAlt });
  }
  return {
    activeCount: inBand.length,
    climate: inBand
      .filter((satellite) => CLIMATE_MISSION.test(satellite.name))
      .sort((a, b) => Math.abs(a.altKm - altKm) - Math.abs(b.altKm - altKm)),
  };
}

export interface AiStep {
  when: string;
  atYear: number;
  title: string;
  detail: string;
  // 'OrbitSentinel' = this platform does it today; 'Research' = published AI work, not built here.
  by: 'OrbitSentinel' | 'Research';
}

/** Where AI helps, step by step through the simulated scenario. Early steps quote the breakup year. */
export function aiTimeline(result: CascadeResult, impact: EarthImpact, known = true): AiStep[] {
  const point = nearestPoint(result, 0);
  const altitude = Math.round(impact.parentAltKm);
  const steps: AiStep[] = [
    {
      when: 'Hours',
      atYear: 0,
      title: `Breakup at ${altitude} km: classify it and size the cloud`,
      detail:
        'Neural networks trained on the NASA breakup model tell a collision from an explosion and estimate the fragment cloud from the first tracking passes, before the catalog catches up (AMOS 2025).',
      by: 'Research',
    },
    {
      when: 'Day 1',
      atYear: 0,
      title: known
        ? `Re-screen ${point.satellitesAtRisk.toLocaleString('en-US')} satellites in the band`
        : 'Re-screen every active satellite in the band',
      detail:
        'Screen every satellite near the cloud against the new fragments, every catalog update.',
      by: 'OrbitSentinel',
    },
    {
      when: 'Week 1',
      atYear: 0,
      title: 'Agree who moves',
      detail: `${known ? `Close approaches rise ${point.extraConjunctionsPct.toFixed(1)}%. ` : ''}For each pair of active satellites, the Negotiator agrees who maneuvers and logs why, using published weights.`,
      by: 'OrbitSentinel',
    },
  ];
  for (const collision of result.secondaryCollisions.slice(0, 3))
    steps.push({
      when: `Year ${collision.year.toFixed(1)}`,
      atYear: collision.year,
      title: `Secondary collision at ${Math.round(collision.altKm)} km`,
      detail: `${collision.fragments.toLocaleString('en-US')} new fragments. Repeat: classify, re-screen, negotiate. Each hit feeds the chain reaction.`,
      by: 'OrbitSentinel',
    });
  if (result.secondaryCollisions.length > 3)
    steps.push({
      when: 'Later',
      atYear: result.secondaryCollisions[3].year,
      title: `${result.secondaryCollisions.length - 3} more secondary collisions`,
      detail: 'The same loop runs for each one.',
      by: 'OrbitSentinel',
    });
  steps.push(
    {
      when: 'Every year',
      atYear: 0,
      title: 'Forecast reentries',
      detail: `About ${impact.reentriesPerYear.toLocaleString('en-US')} fragments a year reenter now. Machine-learning density models forecast the upper atmosphere better than standard models (Acciarini et al., 2024), which sharpens reentry windows for airspace warnings.`,
      by: 'Research',
    },
    {
      when: 'Years',
      atYear: 0,
      title: 'Rank what to remove first',
      detail:
        'Rank the dead objects in the band by how much collision risk they add. The first inspection mission to a dead rocket stage flew in 2024 (Astroscale ADRAS-J).',
      by: 'Research',
    },
  );
  return steps;
}

function nearestPoint(result: CascadeResult, year: number) {
  return result.years.reduce(
    (nearest, p) => (Math.abs(p.year - year) < Math.abs(nearest.year - year) ? p : nearest),
    result.years[0],
  );
}

export interface PreparednessAction {
  phase: 'Prevent' | 'Prepare' | 'Respond';
  title: string;
  detail: string;
}

export function preparednessActions(
  result: CascadeResult,
  impact: EarthImpact,
  year: number,
  known = true,
): PreparednessAction[] {
  const point = nearestPoint(result, year);
  const altitude = Math.round(impact.parentAltKm);
  const actions: PreparednessAction[] = [
    {
      phase: 'Prevent',
      title: 'Stop the first collision',
      detail:
        'Screen daily, agree who moves before closest approach, and log the decision. Every cascade starts with one avoidable hit.',
    },
  ];
  if (impact.persistence !== 'years')
    actions.push({
      phase: 'Prevent',
      title: 'Plan a disposal burn',
      detail: `At ${altitude} km, drag alone takes about ${Math.round(impact.yearsToClear90)} years to clear 90% of fragments. Deorbit satellites within 5 years of end of mission, ESA's new target.`,
    });
  if (result.parent.type === 'ROCKET_BODY' || result.parent.type === 'DEBRIS')
    actions.push({
      phase: 'Prevent',
      title: 'Remove large derelicts',
      detail:
        'Dead rocket bodies and satellites cannot dodge. ESA finds even 90% disposal success is not enough, so the largest derelicts need active removal.',
    });
  actions.push({
    phase: 'Prevent',
    title: 'Passivate at end of life',
    detail:
      'Vent leftover propellant and discharge batteries so a dead object cannot explode into fragments.',
  });
  actions.push(
    {
      phase: 'Prepare',
      title: known
        ? `Raise screening for ${point.satellitesAtRisk.toLocaleString('en-US')} satellites`
        : 'Raise screening for active satellites in the band',
      detail: `${known ? `Close approaches rise ${point.extraConjunctionsPct.toFixed(1)}% in this band. ` : ''}Operators should screen more often and budget extra fuel for avoidance.`,
    },
    {
      phase: 'Prepare',
      title: 'Share orbit data',
      detail:
        'Publish planned trajectories to free services such as Stargaze or TraCSS so every operator screens against the same picture.',
    },
  );
  if (impact.services.length)
    actions.push({
      phase: 'Prepare',
      title: 'Warn exposed services',
      detail: `${[...new Set(impact.services.map((band) => band.service))].join(', ')} operate near ${altitude} km and should plan for higher risk and possible outages.`,
    });
  actions.push(
    {
      phase: 'Respond',
      title: 'Track reentries',
      detail: `About ${impact.reentriesPerYear.toLocaleString('en-US')} fragments a year are reentering now. Most burn up, but parts can reach the ground: an ISS battery-pallet part went through a Florida home (2024, NASA confirmed) and Falcon 9 debris fell in Poland (2025). Publish reentry windows and use controlled reentry for rocket stages.`,
    },
    {
      phase: 'Respond',
      title: 'Monitor the upper atmosphere',
      detail:
        'About 10% of large stratospheric particles already carry spacecraft metals (NOAA). Count reentered mass as an environmental cost.',
    },
  );
  return actions;
}

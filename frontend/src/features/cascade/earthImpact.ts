import type { CascadeResult } from '../../api/types';

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
// - Cosmos 1408 (~480 km, 2021): ~63% of ~1,780 tracked fragments decayed within a year and the rest
//   were expected down by ~2033 (SpaceNews, 2022) → τ ≈ 1 year.
// - Fengyun-1C (~865 km, 2007): ~2,800 of 3,500+ fragments still catalogued after 19 years
//   (Orbital Radar, 2026) → τ = 19 / −ln(0.8) ≈ 85 years.
// Fragments have a high area-to-mass ratio, so they decay faster than intact spacecraft, which ESA
// puts at ~100–150 years from 800 km. Solar-cycle and thermosphere changes are ignored here.
const LOW_ANCHOR = { altKm: 480, tauYears: 1 };
const HIGH_ANCHOR = { altKm: 865, tauYears: 85 };
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
}

// Each fragment source (the breakup at year 0, then every secondary collision at its own altitude)
// decays independently from the moment it happens.
function sources(result: CascadeResult, parentAltKm: number, year: number) {
  return [
    { year: 0, altKm: parentAltKm, fragments: result.fragmentCount },
    ...result.secondaryCollisions.filter((collision) => collision.year <= year),
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
  };
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
): PreparednessAction[] {
  const point = result.years.reduce(
    (nearest, p) => (Math.abs(p.year - year) < Math.abs(nearest.year - year) ? p : nearest),
    result.years[0],
  );
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
      title: `Raise screening for ${point.satellitesAtRisk.toLocaleString('en-US')} satellites`,
      detail: `Close approaches rise ${point.extraConjunctionsPct.toFixed(1)}% in this band. Operators should screen more often and budget extra fuel for avoidance.`,
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
      detail: `About ${impact.reentriesPerYear.toLocaleString('en-US')} fragments a year are reentering now. Most burn up, but large parts can reach the ground, as in Kenya (2024) and Poland (2025). Publish reentry windows and use controlled reentry for rocket stages.`,
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

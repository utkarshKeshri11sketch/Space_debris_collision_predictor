import { describe, expect, it } from 'vitest';
import type { CascadeResult } from '../../api/types';
import {
  aiTimeline,
  breakupMassKg,
  earthImpact,
  satellitesInBand,
  fragmentLifetimeYears,
  meanAltitudeKm,
  persistenceClass,
  preparednessActions,
  remainingFraction,
  servicesNear,
} from './earthImpact';

const meanMotionAt = (altKm: number) =>
  (Math.sqrt(398600.4418 / Math.pow(6378.137 + altKm, 3)) * 86400) / (2 * Math.PI);

function cascade(altKm: number, type: CascadeResult['parent']['type'] = 'ROCKET_BODY') {
  return {
    parent: {
      noradId: 1,
      name: 'TEST',
      type,
      maneuverable: false,
      omm: { MEAN_MOTION: meanMotionAt(altKm) },
    },
    fragmentCount: 1000,
    spreadDvMs: { mean: 80, sd: 30 },
    seed: 1,
    years: [
      { year: 0, trackedTotal: 1, baselineTotal: 1, extraConjunctionsPct: 0, satellitesAtRisk: 10 },
      {
        year: 10,
        trackedTotal: 1,
        baselineTotal: 1,
        extraConjunctionsPct: 12,
        satellitesAtRisk: 40,
      },
    ],
    secondaryCollisions: [{ year: 5, latDeg: 0, lonDeg: 0, altKm, fragments: 500 }],
  } satisfies CascadeResult;
}

describe('cascade Earth-impact model', () => {
  it('recovers mean altitude from OMM mean motion', () => {
    expect(meanAltitudeKm({ MEAN_MOTION: meanMotionAt(840) })).toBeCloseTo(840, 3);
    expect(meanAltitudeKm({ MEAN_MOTION: 0 })).toBeNaN();
  });
  it('reproduces the two calibration clouds', () => {
    // Cosmos 1408: 661 of 1,783 tracked fragments left ~9 months after the breakup.
    expect(remainingFraction(480, 0.75)).toBeCloseTo(661 / 1783, 6);
    // Fengyun-1C: NASA projects about half still in orbit 26 years after the breakup.
    expect(remainingFraction(865, 26)).toBeCloseTo(0.5, 6);
    expect(fragmentLifetimeYears(865)).toBeCloseTo(37.5, 1);
  });
  it('classifies persistence by altitude', () => {
    expect(persistenceClass(450)).toBe('years');
    expect(persistenceClass(780)).toBe('decades');
    expect(persistenceClass(1000)).toBe('centuries');
  });
  it('conserves fragments and adds secondary clouds only after they happen', () => {
    const result = cascade(840);
    const before = earthImpact(result, 4);
    expect(before.inOrbit + before.reentered).toBe(1000);
    expect(before.satellitesPossiblyLost).toBe(0);
    const after = earthImpact(result, 6);
    expect(after.inOrbit + after.reentered).toBe(1500);
    expect(after.satellitesPossiblyLost).toBe(1);
  });
  it('names services exposed in the band', () => {
    expect(servicesNear(800).map((band) => band.service)).toContain(
      'Weather and Earth observation',
    );
    expect(servicesNear(3000)).toEqual([]);
  });
  it('tailors preparedness to altitude and object type', () => {
    const high = preparednessActions(cascade(840), earthImpact(cascade(840), 10), 10);
    expect(high.map((action) => action.title)).toContain('Plan a disposal burn');
    expect(high.map((action) => action.title)).toContain('Remove large derelicts');
    const low = cascade(450, 'PAYLOAD');
    const lowActions = preparednessActions(low, earthImpact(low, 10), 10);
    expect(lowActions.map((action) => action.title)).not.toContain('Plan a disposal burn');
    expect(lowActions.map((action) => action.title)).not.toContain('Remove large derelicts');
    expect(lowActions.every((action) => action.detail.length > 0)).toBe(true);
    // Only confirmed ground-impact events are cited.
    expect(JSON.stringify(high)).not.toContain('Kenya');
    expect(JSON.stringify(high)).toContain('Florida');
  });
  it('tracks reentered mass and alumina, conserving the breakup mass', () => {
    const result = cascade(840);
    expect(breakupMassKg(result.parent)).toBe(1400);
    expect(breakupMassKg({ ...result.parent, noradId: 22285 })).toBe(8900);
    expect(breakupMassKg({ ...result.parent, type: 'DEBRIS' })).toBe(801);
    const early = earthImpact(result, 4);
    // Same share of mass as of fragments (the fragment count is rounded to whole pieces).
    expect(Math.abs(early.reenteredMassKg - 1400 * (early.reentered / 1000))).toBeLessThan(1.4);
    expect(early.aluminaKg).toBeCloseTo(early.reenteredMassKg * 0.12, 6);
    // Far in the future everything reenters: primary 1,400 kg + one 800 kg secondary collision.
    expect(earthImpact(result, 5000).reenteredMassKg).toBeCloseTo(2200, 3);
  });
  it('lists real active payloads in the band and picks out climate missions', () => {
    const object = (noradId: number, name: string, altKm: number, active = true) => ({
      noradId,
      name,
      type: 'PAYLOAD' as const,
      active,
      maneuverable: false,
      omm: { MEAN_MOTION: meanMotionAt(altKm) },
    });
    const band = satellitesInBand(
      [
        object(43013, 'NOAA 20', 824),
        object(2, 'STARLINK-1', 550),
        object(3, 'IRIDIUM 180', 780),
        object(4, 'METOP-B', 817, false),
      ],
      840,
    );
    expect(band.activeCount).toBe(2);
    expect(band.climate.map((satellite) => satellite.name)).toEqual(['NOAA 20']);
  });
  it('builds an AI timeline from the scenario, separating our features from research', () => {
    const result = cascade(840);
    const steps = aiTimeline(result, earthImpact(result, 10));
    // Day-1 steps quote the breakup year, not wherever the slider is.
    expect(steps.some((step) => step.title.includes('Re-screen 10 satellites'))).toBe(true);
    expect(steps.some((step) => step.title === 'Secondary collision at 840 km')).toBe(true);
    expect(new Set(steps.map((step) => step.by))).toEqual(new Set(['OrbitSentinel', 'Research']));
  });
});

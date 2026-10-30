import { describe, expect, it } from 'vitest';
import type { CascadeResult } from '../../api/types';
import {
  earthImpact,
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
    expect(fragmentLifetimeYears(480)).toBeCloseTo(1, 6);
    expect(fragmentLifetimeYears(865)).toBeCloseTo(85, 6);
    // Fengyun-1C: ~80% of fragments still catalogued 19 years after the breakup.
    expect(remainingFraction(865, 19)).toBeCloseTo(0.8, 2);
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
  });
});

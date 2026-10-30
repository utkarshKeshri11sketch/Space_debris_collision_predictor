import { describe, expect, it } from 'vitest';
import { propagate } from 'satellite.js';
import { recordFromOmm } from './omm';
const fixture = {
  OBJECT_NAME: 'SIX DIGIT TEST', NORAD_CAT_ID: 123456789,
  EPOCH: '2026-10-30T00:00:00Z', MEAN_MOTION: '15.05', ECCENTRICITY: '0.0004',
  INCLINATION: '53.2', RA_OF_ASC_NODE: 164, ARG_OF_PERICENTER: 12, MEAN_ANOMALY: 220,
  BSTAR: 0.00001,
};
describe('native OMM to SGP4 initialization', () => {
  it('preserves nine-digit IDs and propagates numeric string fields without TLE conversion', () => {
    const record = recordFromOmm(fixture);
    expect(record.satnum).toBe('123456789');
    const result = propagate(record, new Date(fixture.EPOCH));
    expect(result).not.toBeNull();
    expect(Math.hypot(result!.position.x, result!.position.y, result!.position.z)).toBeGreaterThan(6700);
    expect(Math.hypot(result!.velocity.x, result!.velocity.y, result!.velocity.z)).toBeGreaterThan(7);
  });
  it('accepts a UTC epoch without a trailing Z', () => {
    expect(() => recordFromOmm({ ...fixture, EPOCH: '2026-10-30T00:00:00' })).not.toThrow();
  });
  it('rejects malformed or unbound orbits before handing them to the propagator', () => {
    expect(() => recordFromOmm({ ...fixture, ECCENTRICITY: 1.2 })).toThrow('orbital elements');
    expect(() => recordFromOmm({ ...fixture, NORAD_CAT_ID: 1000000000 })).toThrow('NORAD_CAT_ID');
    expect(() => recordFromOmm({ ...fixture, EPOCH: 'yesterday' })).toThrow('EPOCH');
  });
});

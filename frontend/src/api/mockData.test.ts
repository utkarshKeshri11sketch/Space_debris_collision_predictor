import { describe, expect, it } from 'vitest';
import { getMockCatalog, getMockMeta, getMockCascade, mockConjunctions, OBJECT_COUNT } from './mockData';
import { propagate } from 'satellite.js';
import { recordFromOmm } from '../sim/omm';
describe('offline demonstration contract', () => {
  it('contains a stable full-size OMM catalog and consistent type counts', () => {
    const catalog = getMockCatalog();
    const meta = getMockMeta();
    expect(catalog).toHaveLength(OBJECT_COUNT);
    expect(new Set(catalog.map((object) => object.noradId)).size).toBe(OBJECT_COUNT);
    expect(Object.values(meta.byType).reduce((sum, count) => sum + count, 0)).toBe(OBJECT_COUNT);
    expect(meta.byType.PAYLOAD / OBJECT_COUNT).toBeCloseTo(0.36, 2);
    expect(catalog.some((object) => object.noradId === 25544)).toBe(true);
    expect(catalog.some((object) => Number(object.omm.MEAN_MOTION) < 1.01)).toBe(true);
  });
  it('anchors critical and dual-maneuver events to the required demo story', () => {
    expect(mockConjunctions[0]).toMatchObject({ id: 'iss-cosmos', missDistanceM: 412, pc: 3.1e-4, relSpeedKms: 14.2 });
    expect(mockConjunctions[1].primary.maneuverable && mockConjunctions[1].secondary.maneuverable).toBe(true);
  });
  it('propagates representative LEO, polar, MEO and GEO catalog records a week forward', () => {
    const catalog = getMockCatalog();
    const sample = catalog.filter((_, index) => index < 10 || index % 277 === 0);
    for (const object of sample) {
      const record = recordFromOmm(object.omm);
      const result = propagate(record, new Date(Date.parse(String(object.omm.EPOCH)) + 7 * 86400000));
      expect(result, object.name).not.toBeNull();
      expect(Number.isFinite(result!.position.x), object.name).toBe(true);
      expect(Math.hypot(result!.position.x, result!.position.y, result!.position.z), object.name).toBeGreaterThan(6378);
    }
  });
  it('returns parameters, horizon-limited secondary events and launch-sensitive baselines', () => {
    const request = { noradId: 22285, event: 'collision' as const, years: 10, includeLaunches: true };
    const result = getMockCascade(request);
    expect(result.years).toHaveLength(11);
    expect(result.secondaryCollisions).toHaveLength(1);
    expect(result.fragmentCount).toBe(12784);
    expect(result.years[10].trackedTotal).toBeGreaterThan(result.years[10].baselineTotal);
    expect(getMockCascade({ ...request, includeLaunches: false }).years[10].baselineTotal).toBeLessThan(result.years[10].baselineTotal);
  });
});

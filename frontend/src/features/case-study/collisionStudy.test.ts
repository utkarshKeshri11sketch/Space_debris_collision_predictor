import { describe, expect, it } from 'vitest';
import fixture from '../../api/collisionStudyFixture.json';
import type { CollisionStudy } from '../../api/types';
import { ordinal, pcY, PC_FLOOR, REWIND_2009_ID, studyDate } from './CollisionStudyScreen';

const study = fixture as CollisionStudy;

describe('Rewind 2009 helpers', () => {
  it('shows only the date precision the source gives', () => {
    expect(studyDate('2009-02-10')).toBe('10 Feb 2009');
    expect(studyDate('2013-01')).toBe('Jan 2013');
    expect(studyDate('2023')).toBe('2023');
  });
  it('places Pc on a log scale and clamps tiny values to the floor', () => {
    expect(pcY(1, 0, 120)).toBe(0);
    expect(pcY(1e-4, 0, 120)).toBeCloseTo(40);
    expect(pcY(2.6e-51, 0, 120)).toBe(pcY(PC_FLOOR, 0, 120));
  });
  it('writes ordinals', () => {
    expect([1, 2, 3, 11, 12, 13, 21, 152].map(ordinal)).toEqual([
      '1st',
      '2nd',
      '3rd',
      '11th',
      '12th',
      '13th',
      '21st',
      '152nd',
    ]);
  });
});

describe('Rewind 2009 offline fixture', () => {
  it('matches the id the screen requests and cites only listed sources', () => {
    expect(study.id).toBe(REWIND_2009_ID);
    const keys = new Set(study.sources.map((s) => s.key));
    for (const fact of [...study.facts, ...study.aftermath])
      expect(keys.has(fact.source)).toBe(true);
  });
  it('crosses the burn threshold before the collision only with shared data', () => {
    const above = study.sharedDataPc.filter((p) => p.sharedPc >= study.pcThreshold);
    expect(above.length).toBe(study.sharedDataPc.length);
    expect(study.sharedDataPc.slice(0, -1).every((p) => p.oneSidedPc < study.pcThreshold)).toBe(
      true,
    );
  });
});

import { describe, expect, it } from 'vitest';
import { formatPropellant, propellantBar } from './CaseStudyScreen';

describe('case study formatting', () => {
  it('shows sub-10 g burns in grams', () => {
    expect(formatPropellant(0.1495)).toBe('0.15 kg');
    expect(formatPropellant(0.0003535)).toBe('0.35 g');
  });

  it('keeps a several-hundred-fold gap visible on the log bar', () => {
    const station = propellantBar(0.1495);
    const starlink = propellantBar(0.0003535);
    expect(station).toBeGreaterThan(starlink);
    expect(starlink).toBeGreaterThanOrEqual(3);
    expect(station).toBeLessThanOrEqual(100);
  });
});

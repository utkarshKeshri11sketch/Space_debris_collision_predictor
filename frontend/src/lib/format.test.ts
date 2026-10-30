import { describe, expect, it } from 'vitest';
import { formatCountdown, formatDistance, formatProbability, formatUtc, probabilityOdds } from './format';
describe('operator-facing units and time', () => {
  it('switches metres to kilometres at the unit boundary', () => {
    expect(formatDistance(412)).toBe('412 m');
    expect(formatDistance(1000)).toBe('1.00 km');
    expect(formatDistance(4200)).toBe('4.20 km');
    expect(formatDistance(NaN)).toBe('—');
  });
  it('keeps small probabilities legible and supplies natural odds', () => {
    expect(formatProbability(3.1e-4)).toBe('3.1 × 10⁻⁴');
    expect(probabilityOdds(3.1e-4)).toBe('1 in 3,226');
    expect(formatProbability(0)).toBe('0');
    expect(formatProbability(-1)).toBe('—');
  });
  it('uses UTC and distinguishes upcoming from passed closest approach', () => {
    const now = Date.parse('2026-10-30T00:00:00Z');
    expect(formatCountdown(now + 3601000, now)).toBe('T−01:00:01');
    expect(formatCountdown(now - 61000, now)).toBe('T+00:01:01');
    expect(formatUtc(now)).toBe('00:00:00 UTC');
  });
});

import { describe, expect, it } from 'vitest';
import { weightedTotals } from '../features/negotiator/WeightExplorer';
import { matches, NUMBER_PATTERN, type KnownValue } from './grounding';

const known: KnownValue[] = [
  { kind: 'distance', value: 1561 },
  { kind: 'speed', value: 12.7255 },
  { kind: 'dv', value: 0.03 },
  { kind: 'mass', value: 0.0005303 },
  { kind: 'pc', value: 2.64e-5 },
];
const verified = (text: string) =>
  [...text.matchAll(NUMBER_PATTERN)]
    .filter(([, raw, exponent, unit]) => matches(raw, exponent, unit, known))
    .map(([whole]) => whole);

describe('physics number tags', () => {
  it('matches values within the rounding the text used, across units', () => {
    expect(verified('pass 1.56 km apart at 12.7 km/s')).toEqual(['1.56 km', '12.7 km/s']);
    expect(verified('a 0.03 m/s burn using 0.53 g')).toEqual(['0.03 m/s', '0.53 g']);
    expect(verified('collision probability 2.6 × 10⁻⁵')).toEqual(['2.6 × 10⁻⁵']);
  });

  it('never tags numbers the physics did not produce, or bare numbers', () => {
    expect(verified('a 0.50 m/s burn, 9 km away, round 3, 70% fuel')).toEqual([]);
  });
});

describe('weight explorer totals', () => {
  const criteria = [
    { name: 'Propellant reserve', weight: 0.35, a: 100, b: 86 },
    { name: 'Maneuver cost', weight: 0.25, a: 0, b: 100 },
  ];
  it('uses the same weighted mean as the mediator, and can flip', () => {
    const [a, b] = weightedTotals(criteria, [35, 25]);
    expect(b).toBeGreaterThan(a);
    const [a2, b2] = weightedTotals(criteria, [100, 0]);
    expect(a2).toBeGreaterThan(b2);
  });
});

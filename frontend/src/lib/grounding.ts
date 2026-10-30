/**
 * Client-side check that a number quoted in AI text matches a value the physics engine computed.
 * It only tags numbers it can match; it never edits the text. Unmatched numbers stay plain.
 */
import type { ConjunctionDetail, ManeuverOption, NegotiationEvent } from '../api/types';

type Kind = 'distance' | 'speed' | 'dv' | 'mass' | 'pc';
export interface KnownValue {
  kind: Kind;
  value: number; // base units: m, km/s, m/s, kg, probability
}

const SUPERSCRIPT: Record<string, string> = {
  '⁻': '-',
  '⁰': '0',
  '¹': '1',
  '²': '2',
  '³': '3',
  '⁴': '4',
  '⁵': '5',
  '⁶': '6',
  '⁷': '7',
  '⁸': '8',
  '⁹': '9',
};
// number [× 10^exp] [unit]. Units decide the kind; bare numbers are never tagged.
export const NUMBER_PATTERN =
  /(\d[\d,]*(?:\.\d+)?)(?:\s*×\s*10([⁻⁰¹²³⁴⁵⁶⁷⁸⁹]+))?(?:\s*(m\/s|km\/s|kg|km|g|m)(?![a-zA-Z]))?/g;

function option(o: ManeuverOption): KnownValue[] {
  return [
    { kind: 'dv', value: o.dvMs },
    { kind: 'distance', value: o.newMissM },
    { kind: 'pc', value: o.newPc },
    { kind: 'mass', value: o.propellantKg },
  ];
}

/** Every number the screening, maneuver planner and mediator produced for this event. */
export function knownValues(
  detail: ConjunctionDetail | undefined,
  events: NegotiationEvent[] = [],
): KnownValue[] {
  if (!detail) return [];
  const known: KnownValue[] = [
    { kind: 'distance', value: detail.missDistanceM },
    { kind: 'distance', value: detail.rtnM.r },
    { kind: 'distance', value: detail.rtnM.t },
    { kind: 'distance', value: detail.rtnM.n },
    { kind: 'speed', value: detail.relSpeedKms },
    { kind: 'pc', value: detail.pc },
    ...detail.options.flatMap(option),
  ];
  for (const event of events) if (event.type === 'agreement') known.push(...option(event.maneuver));
  return known;
}

function decimals(text: string): number {
  const dot = text.indexOf('.');
  return dot < 0 ? 0 : text.length - dot - 1;
}

/** Does `raw` (as written, with its unit) match a known value within its own rounding? */
export function matches(
  raw: string,
  exponent: string | undefined,
  unit: string | undefined,
  known: KnownValue[],
): boolean {
  const number = Number(raw.replace(/,/g, ''));
  if (!Number.isFinite(number)) return false;
  let kind: Kind;
  let scale = 1; // multiply a known base value by this to get the text's unit
  if (exponent !== undefined) {
    kind = 'pc';
  } else if (unit === 'm/s') kind = 'dv';
  else if (unit === 'km/s') kind = 'speed';
  else if (unit === 'kg') kind = 'mass';
  else if (unit === 'g') {
    kind = 'mass';
    scale = 1000;
  } else if (unit === 'km') {
    kind = 'distance';
    scale = 1 / 1000;
  } else if (unit === 'm') kind = 'distance';
  else return false;
  if (kind === 'pc') {
    const value =
      number *
      10 **
        Number(
          exponent!
            .split('')
            .map((c) => SUPERSCRIPT[c] ?? c)
            .join(''),
        );
    return known.some(
      (k) => k.kind === 'pc' && k.value > 0 && Math.abs(value - k.value) <= k.value * 0.06,
    );
  }
  const tolerance = 0.5 * 10 ** -decimals(raw);
  return known.some((k) => {
    if (k.kind !== kind) return false;
    const expected = k.value * scale;
    return Math.abs(number - expected) <= Math.max(tolerance, Math.abs(expected) * 0.01);
  });
}

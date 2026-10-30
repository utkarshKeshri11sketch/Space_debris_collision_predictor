import type { ReactNode } from 'react';
import { matches, NUMBER_PATTERN, type KnownValue } from '../lib/grounding';

/** Renders AI text with every number that matches a physics-computed value tagged "physics ✓". */
export function PhysicsText({ text, known }: { text: string; known: KnownValue[] }) {
  const parts: ReactNode[] = [];
  let last = 0;
  let verified = 0;
  for (const match of text.matchAll(NUMBER_PATTERN)) {
    const [whole, raw, exponent, unit] = match;
    if (!matches(raw, exponent, unit, known)) continue;
    const start = match.index ?? 0;
    parts.push(text.slice(last, start));
    parts.push(
      <span
        className="physics-num"
        key={start}
        title="Matches a value computed by the physics engine"
      >
        {whole}
        <sup aria-label="verified against physics">✓</sup>
      </span>,
    );
    last = start + whole.length;
    verified++;
  }
  parts.push(text.slice(last));
  return (
    <>
      <p>{parts}</p>
      {verified > 0 && (
        <small className="physics-count">
          physics ✓ {verified} {verified === 1 ? 'number matches' : 'numbers match'} the computed
          values
        </small>
      )}
    </>
  );
}

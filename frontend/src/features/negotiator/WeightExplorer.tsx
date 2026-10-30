import { useState } from 'react';

interface Criterion {
  name: string;
  weight: number;
  a: number;
  b: number;
}

/** Weighted total, same formula as the backend mediator (app/ai/scoring.py `totals`). */
export function weightedTotals(criteria: Criterion[], weights: number[]): [number, number] {
  const sum = weights.reduce((total, w) => total + w, 0) || 1;
  return [
    criteria.reduce((total, c, i) => total + c.a * weights[i], 0) / sum,
    criteria.reduce((total, c, i) => total + c.b * weights[i], 0) / sum,
  ];
}

/** Lets a viewer move the published weights and see whether the decision would flip. */
export function WeightExplorer({
  criteria,
  chosen,
  nameA,
  nameB,
}: {
  criteria: Criterion[];
  chosen: 'a' | 'b' | null;
  nameA: string;
  nameB: string;
}) {
  const published = criteria.map((c) => Math.round(c.weight <= 1 ? c.weight * 100 : c.weight));
  const [weights, setWeights] = useState(published);
  const [open, setOpen] = useState(false);
  const [a, b] = weightedTotals(criteria, weights);
  const leader = a === b ? null : a > b ? 'a' : 'b';
  const changed = weights.some((w, i) => w !== published[i]);
  const flips = changed && chosen && leader && leader !== chosen;
  if (!open)
    return (
      <button className="weight-explorer-toggle" onClick={() => setOpen(true)}>
        Try other weights →
      </button>
    );
  return (
    <div className="weight-explorer">
      <div className="weight-explorer-head">
        <b>Published weights, open to inspection</b>
        <button onClick={() => setWeights(published)} disabled={!changed}>
          Reset
        </button>
      </div>
      {criteria.map((c, i) => (
        <label key={c.name}>
          <span>{c.name}</span>
          <input
            type="range"
            min={0}
            max={100}
            step={5}
            value={weights[i]}
            onChange={(e) =>
              setWeights((current) => current.map((w, j) => (j === i ? Number(e.target.value) : w)))
            }
          />
          <b>{weights[i]}</b>
        </label>
      ))}
      <p className={`weight-explorer-result ${flips ? 'flipped' : ''}`}>
        A {a.toFixed(1)} · B {b.toFixed(1)} →{' '}
        {leader ? `${leader === 'a' ? nameA : nameB} moves` : 'tie'}
        {flips ? ' · decision flips' : changed ? ' · same decision' : ' · as published'}
      </p>
      <small>
        Weighted totals only. The mediator also requires the burn to reach the safety target.
      </small>
    </div>
  );
}

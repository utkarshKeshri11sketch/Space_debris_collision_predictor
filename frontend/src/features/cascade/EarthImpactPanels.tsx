import type { CascadeResult } from '../../api/types';
import { formatNumber } from '../../lib/format';
import {
  RING_FORMATION_MONTHS,
  earthImpact,
  preparednessActions,
  remainingFraction,
  type Persistence,
} from './earthImpact';
import './earthImpact.css';

const persistenceLabel: Record<Persistence, string> = {
  years: 'Clears within years',
  decades: 'Lingers for decades',
  centuries: 'Lingers for over a century',
};

function PersistenceChart({ altKm, year }: { altKm: number; year: number }) {
  const horizon = 100;
  const x = (t: number) => 36 + (t / horizon) * 272;
  const y = (fraction: number) => 128 - fraction * 104;
  const curve = Array.from({ length: 51 }, (_, i) => {
    const t = (i / 50) * horizon;
    return `${x(t)},${y(remainingFraction(altKm, t))}`;
  }).join(' ');
  const marker = Math.min(year, horizon);
  return (
    <div className="feature-chart">
      <svg
        viewBox="0 0 324 160"
        role="img"
        aria-label="Share of breakup fragments still in orbit over 100 years"
      >
        {[0, 0.5, 1].map((ratio) => (
          <g key={ratio}>
            <line x1="36" x2="308" y1={y(ratio)} y2={y(ratio)} className="chart-grid" />
            <text x="30" y={y(ratio) + 4} textAnchor="end">
              {ratio * 100}%
            </text>
          </g>
        ))}
        <line x1={x(marker)} x2={x(marker)} y1="18" y2="132" className="chart-threshold" />
        <polyline points={curve} className="chart-line chart-line-orange" />
        <text x="36" y="148">
          Year 0
        </text>
        <text x="308" y="148" textAnchor="end">
          Year {horizon}
        </text>
      </svg>
    </div>
  );
}

export function EarthImpactPanel({ result, year }: { result: CascadeResult; year: number }) {
  const impact = earthImpact(result, year);
  const altitude = Math.round(impact.parentAltKm);
  return (
    <div className="earth-impact">
      <div className={`earth-persistence ${impact.persistence}`}>
        <span className="eyebrow">Orbital pollution at {altitude} km</span>
        <strong>{persistenceLabel[impact.persistence]}</strong>
        <p>
          90% of fragments reenter after about {formatNumber(Math.round(impact.yearsToClear90))}{' '}
          years. {Math.round(impact.remainingAfter100Years * 100)}% would still be in orbit after
          100 years.
        </p>
      </div>
      <dl className="cascade-impact-stats">
        <div>
          <dt>Fragments still in orbit</dt>
          <dd>{formatNumber(impact.inOrbit)}</dd>
        </div>
        <div>
          <dt>Reentered so far</dt>
          <dd>{formatNumber(impact.reentered)}</dd>
        </div>
        <div>
          <dt>Ring around Earth forms in</dt>
          <dd>
            ~{RING_FORMATION_MONTHS.min}–{RING_FORMATION_MONTHS.max}
            <small> months</small>
          </dd>
        </div>
      </dl>
      <section className="feature-section">
        <div className="feature-subheading">
          <h3>Fragments still in orbit</h3>
          <span>Breakup cloud, 100 years</span>
        </div>
        <PersistenceChart altKm={impact.parentAltKm} year={year} />
      </section>
      <section className="feature-section">
        <div className="feature-subheading">
          <h3>Effects on Earth</h3>
          <span>Year {Math.round(year)}</span>
        </div>
        <ul className="earth-effects">
          <li>
            <b>{formatNumber(impact.reentriesPerYear)} reentries a year</b>
            <span>
              Most burn up and leave metals in the stratosphere. About 10% of large stratospheric
              particles already contain spacecraft metals.
            </span>
          </li>
          <li>
            <b>Falling debris</b>
            <span>
              Large parts can survive reentry, as in Kenya (Dec 2024) and Poland (Feb 2025).
            </span>
          </li>
          <li>
            <b>Up to {impact.satellitesPossiblyLost} replacement launches</b>
            <span>
              Each secondary collision can destroy a working satellite, and every replacement adds
              launch soot and a future reentry.
            </span>
          </li>
          {impact.services.length ? (
            <li>
              <b>Services in this band</b>
              <span>
                {impact.services.map((band) => `${band.service} (${band.examples})`).join('; ')}.
              </span>
            </li>
          ) : null}
        </ul>
      </section>
      <p className="feature-footnote">
        Fragment lifetimes are fitted to the real Cosmos 1408 and Fengyun-1C clouds. Solar minimum
        and a cooling, shrinking thermosphere both lengthen them; MIT projects low orbit could hold
        50–66% fewer satellites by 2100.
      </p>
    </div>
  );
}

export function PreparednessPanel({ result, year }: { result: CascadeResult; year: number }) {
  const actions = preparednessActions(result, earthImpact(result, year), year);
  return (
    <div className="earth-impact">
      <p className="feature-description">
        What operators, agencies and governments can do to prevent this cascade and prepare for it.
      </p>
      <ol className="preparedness-list">
        {actions.map((action) => (
          <li key={action.title}>
            <span className={`preparedness-phase ${action.phase.toLowerCase()}`}>
              {action.phase}
            </span>
            <b>{action.title}</b>
            <p>{action.detail}</p>
          </li>
        ))}
      </ol>
    </div>
  );
}

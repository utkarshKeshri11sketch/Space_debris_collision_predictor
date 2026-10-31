import { useState } from 'react';
import { useCollisionStudy } from '../../api/hooks';
import type { CollisionStudy } from '../../api/types';
import {
  formatDistance,
  formatNumber,
  formatProbability,
  formatPropellant,
} from '../../lib/format';
import { remainingFraction, yearsToClear } from '../cascade/earthImpact';
import './caseStudy.css';
import './collisionStudy.css';

export const REWIND_2009_ID = 'case-2009-02-10-iridium33-cosmos2251';

type View = 'reality' | 'sentinel';

/** Study dates are YYYY, YYYY-MM or YYYY-MM-DD; show only the precision the source gives. */
export function studyDate(value: string): string {
  const [year, month, day] = value.split('-');
  if (!month) return year;
  const date = new Date(Date.UTC(Number(year), Number(month) - 1, Number(day ?? 1)));
  return date.toLocaleDateString('en-GB', {
    ...(day ? { day: 'numeric' } : {}),
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  });
}

/** Log-scale Pc chart: 1 at the top, 1e-12 and anything smaller at the floor. */
export const PC_FLOOR = 1e-12;
export function pcY(pc: number, top: number, bottom: number): number {
  const decades = -Math.log10(Math.max(pc, PC_FLOOR));
  return top + (Math.min(decades, 12) / 12) * (bottom - top);
}

export function ordinal(n: number): string {
  const teen = n % 100 >= 11 && n % 100 <= 13;
  return `${n}${teen ? 'th' : (({ 1: 'st', 2: 'nd', 3: 'rd' } as Record<number, string>)[n % 10] ?? 'th')}`;
}

const yearsBetween = (from: string, to: string) =>
  (Date.parse(to.length === 7 ? `${to}-01` : to) - Date.parse(from)) / (365.25 * 86400000);

function CrossingDiagram({ data, view }: { data: CollisionStudy; view: View }) {
  const [iridium, cosmos] = data.objects;
  const iridiumPath = 'M 40 180 Q 300 100 560 20';
  const cosmosPath = 'M 40 20 Q 300 100 560 180';
  const dodge = 'M 40 180 Q 260 30 560 8';
  const reduceMotion =
    typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
  const collided = view === 'reality';
  return (
    <svg
      className="cs-diagram"
      viewBox="0 0 600 200"
      role="img"
      aria-label={
        collided
          ? `${iridium.name} and ${cosmos.name} collide at ${data.relSpeedKms} km/s`
          : `${iridium.name} burns ${data.orbitSentinel.maneuver.dvMs} m/s and passes ${formatDistance(data.orbitSentinel.maneuver.newMissM)} away`
      }
    >
      <path className="cs-orbit cs-orbit-station" d={iridiumPath} />
      <path className="cs-orbit rw-orbit-dead" d={cosmosPath} />
      {!collided && <path key={view} className="cs-dodge" d={dodge} />}
      <circle className="cs-crossing" cx="300" cy="100" r="14" />
      {collided ? (
        <g className="rw-burst" aria-hidden="true">
          {Array.from({ length: 14 }, (_, i) => {
            const angle = (i / 14) * Math.PI * 2;
            const reach = 22 + (i % 3) * 9;
            return (
              <circle
                key={i}
                r={i % 2 ? 1.6 : 2.4}
                cx={300 + Math.cos(angle) * reach}
                cy={100 + Math.sin(angle) * reach * 0.7}
              />
            );
          })}
        </g>
      ) : reduceMotion ? (
        <>
          <circle className="cs-body cs-body-station" r="5" cx="236" cy="62" />
          <circle className="cs-body rw-body-dead" r="6" cx="250" cy="88" />
        </>
      ) : (
        <>
          <circle className="cs-body cs-body-station" r="5">
            <animateMotion dur="6s" repeatCount="indefinite" path={dodge} />
          </circle>
          <circle className="cs-body rw-body-dead" r="6">
            <animateMotion dur="6s" repeatCount="indefinite" path={cosmosPath} />
          </circle>
        </>
      )}
      <text className="cs-crossing-label" x="318" y="128">
        {collided
          ? `collision · ${data.relSpeedKms} km/s`
          : `${formatDistance(data.orbitSentinel.maneuver.newMissM)} miss`}
      </text>
      <text className="cs-label" x="44" y="194">
        {iridium.name} · {iridium.massKg} kg · {iridium.status}
      </text>
      <text className="cs-label" x="44" y="14">
        {cosmos.name} · {cosmos.massKg} kg · {cosmos.status}
      </text>
      <text className="cs-mover" x="590" y="194" textAnchor="end">
        {collided ? 'nobody burns' : `${iridium.name} burns`}
      </text>
    </svg>
  );
}

function PcChart({ data }: { data: CollisionStudy }) {
  const [top, bottom, left, right] = [16, 150, 64, 560];
  const t0 = Date.parse(data.sharedDataPc[0].at);
  const t1 = Date.parse(data.tca);
  const x = (iso: string) => left + ((Date.parse(iso) - t0) / (t1 - t0)) * (right - left);
  const series = (key: 'sharedPc' | 'oneSidedPc') =>
    data.sharedDataPc.map((p) => `${x(p.at)},${pcY(p[key], top, bottom)}`).join(' ');
  const threshold = pcY(data.pcThreshold, top, bottom);
  return (
    <svg
      className="rw-chart"
      viewBox="0 0 600 182"
      role="img"
      aria-label="Collision probability by screening date: above the burn threshold from 7 February with shared data, negligible with one side's data until the last day"
    >
      {[1, 1e-4, 1e-8, PC_FLOOR].map((pc) => (
        <g key={pc}>
          <line
            className="chart-grid"
            x1={left}
            x2={right}
            y1={pcY(pc, top, bottom)}
            y2={pcY(pc, top, bottom)}
          />
          <text className="rw-axis" x={left - 8} y={pcY(pc, top, bottom) + 4} textAnchor="end">
            {pc === 1
              ? '1'
              : pc === PC_FLOOR
                ? '≤ 10⁻¹²'
                : formatProbability(pc).replace('1.0 × ', '')}
          </text>
        </g>
      ))}
      <line className="rw-threshold" x1={left} x2={right} y1={threshold} y2={threshold} />
      {/* Below the line: the shared-data values sit just above it. */}
      <text className="rw-threshold-label" x={left + 12} y={threshold + 13}>
        burn threshold (10⁻⁴)
      </text>
      <line className="rw-impact" x1={right} x2={right} y1={top} y2={bottom} />
      <text className="rw-impact-label" x={right} y={bottom + 28} textAnchor="end">
        collision
      </text>
      <polyline className="rw-line rw-line-one" points={series('oneSidedPc')} />
      <polyline className="rw-line rw-line-shared" points={series('sharedPc')} />
      {data.sharedDataPc.map((p) => (
        <g key={p.at}>
          <circle
            className="rw-dot rw-dot-one"
            r="3"
            cx={x(p.at)}
            cy={pcY(p.oneSidedPc, top, bottom)}
          />
          <circle
            className="rw-dot rw-dot-shared"
            r="3.5"
            cx={x(p.at)}
            cy={pcY(p.sharedPc, top, bottom)}
          />
          <text
            className="rw-value"
            x={x(p.at)}
            y={pcY(p.sharedPc, top, bottom) - 8}
            textAnchor="middle"
          >
            {formatProbability(p.sharedPc)}
          </text>
          <text className="rw-axis" x={x(p.at)} y={bottom + 16} textAnchor="middle">
            {studyDate(p.at.slice(0, 10)).replace(' 2009', '')}
          </text>
        </g>
      ))}
    </svg>
  );
}

function Timeline({ data }: { data: CollisionStudy }) {
  const source = (key: string) => data.sources.find((s) => s.key === key);
  return (
    <section className="cs-column cs-reality">
      <span className="eyebrow">2009 · data in two silos</span>
      <h3>What happened</h3>
      <ol className="cs-timeline">
        {[...data.facts, ...data.aftermath].map((row, i) => {
          const s = source(row.source);
          return (
            <li key={i}>
              <time>{studyDate(row.date)}</time>
              <p>
                {row.text}{' '}
                {s && (
                  <a href={s.url} target="_blank" rel="noreferrer" title={s.label}>
                    source
                  </a>
                )}
              </p>
            </li>
          );
        })}
      </ol>
      <div className="cs-verdict cs-verdict-bad">
        Collision at {data.relSpeedKms} km/s · both satellites destroyed
      </div>
    </section>
  );
}

function SentinelSteps({ data }: { data: CollisionStudy }) {
  const decision = data.orbitSentinel;
  const burn = decision.maneuver;
  const lastShared = data.sharedDataPc.find((p) =>
    p.at.startsWith(decision.planningAt.slice(0, 10)),
  );
  return (
    <section className="cs-column cs-sentinel">
      <span className="eyebrow">With OrbitSentinel</span>
      <h3>Detect, decide, foresee</h3>
      <ol className="rw-steps">
        <li>
          <b>Detect · on both sides&apos; data</b>
          <p>
            Screening only works on the data it is given. Iridium had the planned burn; the military
            had the precise catalog. Merged, the risk crossed the burn threshold on 7 February. On
            the planned trajectory, OrbitSentinel&apos;s collision probability for 9 February is{' '}
            {formatProbability(decision.pc)}
            {lastShared ? ` (Iridium's own replay: ${formatProbability(lastShared.sharedPc)})` : ''}
            .
          </p>
        </li>
        <li>
          <b>Decide · only one side can move</b>
          <p>
            Cosmos 2251 was dead, so Iridium 33 moves: {burn.label}. The miss grows to{' '}
            {formatDistance(burn.newMissM)} (Pc {formatProbability(burn.newPc)}) for{' '}
            {formatPropellant(burn.propellantKg)} of hydrazine. The burns that set up the collision
            used {formatPropellant(decision.causePropellantKg)}.
          </p>
        </li>
        <li>
          <b>Foresee · what not moving costs</b>
          <p>
            The Cascade Lab&apos;s breakup model predicts {formatNumber(data.debris.modelFragments)}{' '}
            fragments of 10 cm or more at {data.debris.altitudeKm} km. Reality was worse: see below.
          </p>
        </li>
      </ol>
      <div className="cs-verdict cs-verdict-good">
        {data.objects[0].name} moves {burn.dvMs.toFixed(2)} m/s ·{' '}
        {formatPropellant(burn.propellantKg)} of fuel · no debris
      </div>
    </section>
  );
}

function DebrisCost({ data, onCascade }: { data: CollisionStudy; onCascade: () => void }) {
  const latest = data.debris.counts[data.debris.counts.length - 1];
  const years = yearsBetween(data.tca, latest.date);
  const alt = data.debris.altitudeKm;
  const shortfall = 1 - data.debris.modelFragments / latest.catalogued;
  return (
    <section className="rw-debris" aria-label="What the collision cost">
      <div className="feature-subheading">
        <h3>What not moving cost</h3>
        <span>Real catalogue vs the Cascade Lab model</span>
      </div>
      <dl className="rw-stats">
        <div>
          <dt>Fragments catalogued</dt>
          <dd>{formatNumber(latest.catalogued)}</dd>
          <small>by {studyDate(latest.date)}</small>
        </div>
        <div>
          <dt>Still in orbit</dt>
          <dd>{latest.inOrbit !== null ? formatNumber(latest.inOrbit) : '—'}</dd>
          <small>by {studyDate(latest.date)}</small>
        </div>
        <div>
          <dt>Breakup model</dt>
          <dd>{formatNumber(data.debris.modelFragments)}</dd>
          <small>{Math.round(shortfall * 100)}% fewer than catalogued</small>
        </div>
        <div>
          <dt>New close approaches</dt>
          <dd>{formatNumber(data.debris.knockOnConjunctionsPerWeek)}</dd>
          <small>a week, Iridium + Orbcomm (Aug 2009)</small>
        </div>
      </dl>
      <p className="feature-footnote">
        The NASA standard breakup model, which the Cascade Lab uses, underestimates this collision:
        cascade numbers in the Lab are a floor, not a ceiling. Its lifetime model does better: at{' '}
        {alt} km it keeps {Math.round(remainingFraction(alt, years) * 100)}% of fragments in orbit
        after {years.toFixed(1)} years, against{' '}
        {latest.inOrbit !== null ? Math.round((latest.inOrbit / latest.catalogued) * 100) : '—'}% in
        NASA&apos;s count, and clears 90% after about {Math.round(yearsToClear(alt))} years.
      </p>
      <button className="feature-button" onClick={onCascade}>
        Simulate a breakup in the Cascade Lab
      </button>
    </section>
  );
}

function Comparison({ data }: { data: CollisionStudy }) {
  const decision = data.orbitSentinel;
  const totalCauseDv = data.causeBurns.reduce((sum, b) => sum + b.dvMs, 0);
  const latest = data.debris.counts[data.debris.counts.length - 1];
  return (
    <section className="cs-compare" aria-label="Comparison">
      <div className="cs-compare-head">
        <span />
        <span>2009 reality</span>
        <span>With OrbitSentinel</span>
      </div>
      <div className="cs-row">
        <span>Burn</span>
        <span>
          {data.causeBurns.length} × {data.causeBurns[0].dvMs.toFixed(4)} m/s station-keeping
          <small className="cs-cell-note">
            {totalCauseDv.toFixed(4)} m/s, {formatPropellant(decision.causePropellantKg)}: onto the
            collision course
          </small>
        </span>
        <span className="good">
          {decision.maneuver.label}
          <small className="cs-cell-note">
            {formatPropellant(decision.maneuver.propellantKg)} of hydrazine
          </small>
        </span>
      </div>
      <div className="cs-row">
        <span>Result</span>
        <span>Collision at {data.relSpeedKms} km/s</span>
        <span className="good">
          {formatDistance(decision.maneuver.newMissM)} miss, Pc{' '}
          {formatProbability(decision.maneuver.newPc)}
        </span>
      </div>
      <div className="cs-row">
        <span>Debris</span>
        <span>{formatNumber(latest.catalogued)} fragments catalogued</span>
        <span className="good">None</span>
      </div>
      <div className="cs-row">
        <span>Data</span>
        <span>Split: Iridium had the burn plan, the military had the catalog</span>
        <span className="good">Shared, screened, decision logged for a human to approve</span>
      </div>
    </section>
  );
}

export default function CollisionStudyScreen({ onCascade }: { onCascade: () => void }) {
  const query = useCollisionStudy(REWIND_2009_ID);
  const [view, setView] = useState<View>('reality');
  const data = query.data;
  const warning = data?.publicWarning;
  return (
    <div className="case-study" aria-busy={query.isPending}>
      <header className="cs-header">
        <div>
          <span className="eyebrow">Cascade Lab · Rewind 2009 · a real collision replayed</span>
          <h2>{data ? `${data.title} · ${studyDate(data.date)}` : 'Loading case study…'}</h2>
        </div>
        <button className="feature-button" onClick={onCascade}>
          Back to Cascade Lab
        </button>
      </header>
      {query.isError && (
        <div className="feature-state">
          <h3>Case study unavailable</h3>
          <p>{query.error?.message}</p>
          <button className="feature-button" onClick={() => void query.refetch()}>
            Retry
          </button>
        </div>
      )}
      {data && warning && (
        <>
          <div className="cs-rewind" aria-label="Headline comparison">
            <div className="cs-rewind-side bad">
              <span>2009 · data in two silos</span>
              <strong>Collision at {data.relSpeedKms} km/s</strong>
              <small>
                First accidental collision of two satellites;{' '}
                {formatNumber(data.debris.counts[data.debris.counts.length - 1].catalogued)}{' '}
                fragments catalogued.
              </small>
            </div>
            <div className="cs-rewind-side good">
              <span>With OrbitSentinel</span>
              <strong>
                Avoidable for {formatPropellant(data.orbitSentinel.maneuver.propellantKg)} of fuel
              </strong>
              <small>With both sides&apos; data shared, the risk showed from 7 February.</small>
            </div>
          </div>
          <div className="cs-stage">
            <div className="cs-toggle" role="radiogroup" aria-label="Scenario">
              <button
                role="radio"
                aria-checked={view === 'reality'}
                className={view === 'reality' ? 'active bad' : ''}
                onClick={() => setView('reality')}
              >
                2009: what happened
              </button>
              <button
                role="radio"
                aria-checked={view === 'sentinel'}
                className={view === 'sentinel' ? 'active good' : ''}
                onClick={() => setView('sentinel')}
              >
                With OrbitSentinel
              </button>
            </div>
            <CrossingDiagram data={data} view={view} />
          </div>
          <section className="rw-warning">
            <div className="feature-subheading">
              <h3>The warning was in the data, split in two</h3>
              <span>Collision probability by screening date</span>
            </div>
            <PcChart data={data} />
            <p className="rw-legend">
              <i className="rw-key rw-key-shared" /> Both sides&apos; data merged
              <i className="rw-key rw-key-one" /> Military catalog alone · values from
              Iridium&apos;s 2023 replay.
            </p>
            <p className="feature-footnote">
              Free public screening (TLE data) listed the approach in all {warning.reports} reports
              of the week, between {formatDistance(warning.minMissM)} and{' '}
              {formatDistance(warning.maxMissM)}. The last report said{' '}
              {formatDistance(warning.finalMissM)} and ranked it {ordinal(warning.finalRank)}: with
              data that coarse, it could not stand out.
            </p>
          </section>
          <div className="cs-columns">
            <Timeline data={data} />
            <SentinelSteps data={data} />
          </div>
          <DebrisCost data={data} onCascade={onCascade} />
          <Comparison data={data} />
          <footer className="cs-footnote">
            The encounter is reconstructed from published orbits, not historical element sets. Pc
            over time is quoted from Iridium&apos;s replay; the burn and debris model use the same
            physics as live events.
            <details>
              <summary>All modelling assumptions ({data.assumptions.length})</summary>
              <ul>
                {data.assumptions.map((a, i) => (
                  <li key={i}>{a}</li>
                ))}
              </ul>
            </details>
            <details>
              <summary>Sources ({data.sources.length})</summary>
              <ul>
                {data.sources.map((s) => (
                  <li key={s.key}>
                    <a href={s.url} target="_blank" rel="noreferrer">
                      {s.label}
                    </a>
                  </li>
                ))}
              </ul>
            </details>
          </footer>
        </>
      )}
    </div>
  );
}

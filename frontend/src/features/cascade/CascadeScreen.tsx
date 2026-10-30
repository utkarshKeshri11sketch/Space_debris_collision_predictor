import { useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useCascade, useCatalog } from '../../api/hooks';
import type { CascadeResult } from '../../api/types';
import { formatNumber } from '../../lib/format';

interface Props {
  onResult: (result: CascadeResult | undefined) => void;
  onYear: (year: number) => void;
}

function GrowthChart({ result, year }: { result: CascadeResult; year: number }) {
  const data = result.years;
  const maxYear = Math.max(1, ...data.map((point) => point.year));
  const minimum = Math.min(...data.map((point) => point.baselineTotal)) * 0.96;
  const maximum = Math.max(...data.map((point) => point.trackedTotal)) * 1.04;
  const x = (value: number) => 44 + (value / maxYear) * 256;
  const y = (value: number) => 141 - ((value - minimum) / Math.max(1, maximum - minimum)) * 117;
  const baseline = data.map((point) => `${x(point.year)},${y(point.baselineTotal)}`).join(' ');
  const breakup = data.map((point) => `${x(point.year)},${y(point.trackedTotal)}`).join(' ');
  return (
    <div className="feature-chart">
      <svg
        viewBox="0 0 324 184"
        role="img"
        aria-label="Tracked object population with and without the modeled breakup"
      >
        <g>
          {[0, 0.5, 1].map((ratio) => {
            const value = minimum + ratio * (maximum - minimum);
            return (
              <g key={ratio}>
                <line x1="44" x2="300" y1={y(value)} y2={y(value)} className="chart-grid" />
                <text x="36" y={y(value) + 4} textAnchor="end">
                  {(value / 1000).toFixed(0)}k
                </text>
              </g>
            );
          })}
        </g>
        <line x1={x(year)} x2={x(year)} y1="18" y2="146" className="chart-threshold" />
        <polyline points={baseline} className="chart-line chart-line-muted" />
        <polyline points={breakup} className="chart-line chart-line-orange" />
        {result.secondaryCollisions.map((collision, index) => {
          const point = data.find((p) => p.year >= collision.year);
          return (
            point && (
              <circle
                key={index}
                cx={x(collision.year)}
                cy={y(point.trackedTotal)}
                r="4"
                fill="var(--debris)"
                stroke="var(--bg-base)"
                strokeWidth="2"
              />
            )
          );
        })}
        <text x="44" y="166">
          Year 0
        </text>
        <text x="300" y="166" textAnchor="end">
          Year {maxYear}
        </text>
      </svg>
      <div className="chart-legend">
        <span>
          <i className="legend-line orange" />
          With breakup
        </span>
        <span>
          <i className="legend-line muted" />
          Baseline
        </span>
      </div>
    </div>
  );
}

export default function CascadeScreen({ onResult, onYear }: Props) {
  const catalog = useCatalog();
  const simulation = useCascade();
  // "What if this one hits?" from a conjunction: /cascade?norad=<primary>&from=<conjunction id>
  const [params] = useSearchParams();
  const whatIfNorad = Number(params.get('norad')) || 0;
  const whatIfFrom = params.get('from');
  const autoRan = useRef(false);
  const candidates = useMemo(() => {
    const presets =
      catalog.data?.filter(
        (object) =>
          object.name === 'SL-16 R/B' ||
          object.name === 'FENGYUN 1C DEB' ||
          object.name === 'IRIDIUM 33 DEB',
      ) ?? [];
    const whatIf = catalog.data?.find((object) => object.noradId === whatIfNorad);
    return (whatIf ? [whatIf, ...presets.filter((o) => o.noradId !== whatIfNorad)] : presets).slice(
      0,
      12,
    );
  }, [catalog.data, whatIfNorad]);
  const [noradId, setNoradId] = useState<number>(0);
  const [event, setEvent] = useState<'collision' | 'explosion'>('collision');
  const [years, setYears] = useState(25);
  const [launches, setLaunches] = useState(true);
  const [year, setYear] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [activeLength, setActiveLength] = useState(25);
  const [result, setResult] = useState<CascadeResult | undefined>();
  useEffect(() => {
    if (whatIfNorad && candidates.some((object) => object.noradId === whatIfNorad)) {
      if (!autoRan.current) setNoradId(whatIfNorad);
      return;
    }
    if (!noradId && candidates.length)
      setNoradId(
        candidates.find((object) => object.name === 'SL-16 R/B')?.noradId ?? candidates[0].noradId,
      );
  }, [candidates, noradId, whatIfNorad]);
  useEffect(() => {
    if (!playing || !result) return;
    let last = performance.now();
    const timer = window.setInterval(() => {
      const now = performance.now();
      const elapsed = (now - last) / 1000;
      last = now;
      setYear((value) => {
        const next = Math.min(activeLength, value + elapsed * 0.85);
        if (next >= activeLength) setPlaying(false);
        return next;
      });
    }, 50);
    return () => window.clearInterval(timer);
  }, [playing, result, activeLength]);
  useEffect(() => {
    onYear(year);
  }, [year, onYear]);
  const run = () => {
    setPlaying(false);
    setYear(0);
    setResult(undefined);
    onResult(undefined);
    setActiveLength(years);
    simulation.mutate(
      { noradId, event, years, includeLaunches: launches },
      {
        onSuccess: (next) => {
          setResult(next);
          onResult(next);
          setYear(0);
          setPlaying(true);
        },
      },
    );
  };
  // Run the what-if scenario once, as soon as its parent object is selected.
  useEffect(() => {
    if (!whatIfNorad || autoRan.current || noradId !== whatIfNorad) return;
    autoRan.current = true;
    run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [noradId, whatIfNorad]);
  const reset = () => {
    setPlaying(false);
    setYear(0);
    setResult(undefined);
    onResult(undefined);
    simulation.reset();
  };
  const current = result?.years.reduce(
    (nearest, point) =>
      Math.abs(point.year - year) < Math.abs(nearest.year - year) ? point : nearest,
    result.years[0],
  );
  const collisionCount =
    result?.secondaryCollisions.filter((collision) => collision.year <= year).length ?? 0;
  const parent = catalog.data?.find((object) => object.noradId === noradId);
  return (
    <>
      <aside className="route-panel route-panel-left feature-panel cascade-controls">
        <header className="feature-panel-heading">
          <span className="eyebrow">Cascade Lab</span>
          <span className="feature-status">Approximate model</span>
        </header>
        <h2 className="feature-title">Breakup simulation</h2>
        <p className="feature-description">
          Explore how a single event reshapes the orbital environment.
        </p>
        {whatIfFrom && parent?.noradId === whatIfNorad && (
          <div className="what-if-banner" role="status">
            <b>What if it hits?</b> Simulating the collision that breaks up {parent.name}, from a
            screened conjunction. This is the consequence a missed avoidance would leave behind.
          </div>
        )}
        <fieldset disabled={simulation.isPending} className="cascade-fieldset">
          <label className="feature-field">
            Parent object
            <select
              value={noradId}
              onChange={(e) => setNoradId(Number(e.target.value))}
              disabled={catalog.isPending || !candidates.length}
            >
              {!candidates.length && (
                <option value="0">
                  {catalog.isPending ? 'Loading catalog…' : 'No breakup candidates available'}
                </option>
              )}
              {candidates.map((object) => (
                <option key={object.noradId} value={object.noradId}>
                  {object.name} · {object.noradId}
                </option>
              ))}
            </select>
          </label>
          {parent && (
            <div className="cascade-object-meta">
              <span>{parent.type.replace('_', ' ')}</span>
              <b>{Number(parent.omm.INCLINATION).toFixed(1)}° inclination</b>
            </div>
          )}
          {catalog.isError && (
            <div className="feature-stream-error">
              <p>Catalog could not load. Simulation requires a parent orbit.</p>
              <button className="feature-button" onClick={() => void catalog.refetch()}>
                Retry catalog
              </button>
            </div>
          )}
          <div className="feature-field">
            <span>Breakup event</span>
            <div className="feature-segmented">
              <button
                className={event === 'collision' ? 'active' : ''}
                aria-pressed={event === 'collision'}
                onClick={() => setEvent('collision')}
              >
                Collision
              </button>
              <button
                className={event === 'explosion' ? 'active' : ''}
                aria-pressed={event === 'explosion'}
                onClick={() => setEvent('explosion')}
              >
                Explosion
              </button>
            </div>
          </div>
          <label className="feature-field">
            Simulation horizon <b className="field-value">{years} years</b>
            <input
              type="range"
              min="1"
              max="25"
              step="1"
              value={years}
              onChange={(e) => setYears(Number(e.target.value))}
            />
            <span className="range-endpoints">
              <small>1 year</small>
              <small>25 years</small>
            </span>
          </label>
          <label className="feature-checkbox">
            <input
              type="checkbox"
              checked={launches}
              onChange={(e) => setLaunches(e.target.checked)}
            />
            <span>
              Include planned launches<small>Illustrative deployment scenario</small>
            </span>
          </label>
          <button
            className="feature-button primary full-width"
            disabled={!noradId || simulation.isPending}
            onClick={run}
          >
            {simulation.isPending
              ? 'Computing fragment evolution…'
              : result
                ? 'Run new simulation ↗'
                : 'Run simulation ↗'}
          </button>
          {result && (
            <button className="feature-button full-width" onClick={reset}>
              Reset laboratory
            </button>
          )}
        </fieldset>
        <section className="feature-section model-note">
          <span className="eyebrow">Behind the model</span>
          <p>
            Seeded velocity kicks spread fragments along the parent orbit. Differential orbital
            periods and J₂ precession gradually turn the cloud into a debris band.
          </p>
          <small>
            An illustrative long-term model. Results are not operational collision forecasts.
          </small>
        </section>
      </aside>
      <aside className="route-panel route-panel-right feature-panel cascade-results">
        <header className="feature-panel-heading">
          <span className="eyebrow">Projected consequences</span>
          <span className="feature-status">
            {result ? `Year ${year.toFixed(1)}` : 'Awaiting simulation'}
          </span>
        </header>
        {simulation.isPending ? (
          <div className="cascade-empty" aria-busy="true">
            <div className="cascade-orbit-spinner" />
            <h3>Computing fragment evolution</h3>
            <p>Generating fragment parameters and screening the long-term population.</p>
          </div>
        ) : simulation.isError ? (
          <div className="feature-state" role="alert">
            <h3>Simulation interrupted</h3>
            <p>{simulation.error.message}</p>
            <button className="feature-button" onClick={run}>
              Run again
            </button>
          </div>
        ) : !result ? (
          <div className="cascade-empty">
            <svg className="cascade-empty-glyph" viewBox="0 0 180 140" aria-hidden="true">
              <circle cx="90" cy="70" r="38" />
              <ellipse cx="90" cy="70" rx="78" ry="25" transform="rotate(-30 90 70)" />
              <circle cx="149" cy="38" r="4" />
              <path d="M84 56l14 28m-28-8l36-12" />
            </svg>
            <h3>No simulation results</h3>
            <p>
              Choose an object and run a breakup to compare its orbital legacy with the baseline.
            </p>
            <span className="eyebrow">0–25 year evolution</span>
          </div>
        ) : (
          <>
            <h2 className="feature-title">Simulation results</h2>
            <div className="cascade-fragment-stat">
              <strong>{formatNumber(result.fragmentCount)}</strong>
              <span>new fragments &gt; 10 cm</span>
            </div>
            <dl className="cascade-impact-stats">
              <div>
                <dt>Satellites at higher risk</dt>
                <dd>{formatNumber(current?.satellitesAtRisk ?? 0)}</dd>
              </div>
              <div>
                <dt>Extra close approaches</dt>
                <dd>
                  +{(current?.extraConjunctionsPct ?? 0).toFixed(1)}
                  <small>%</small>
                </dd>
              </div>
              <div>
                <dt>Secondary collisions</dt>
                <dd>
                  {collisionCount}
                  <small> events</small>
                </dd>
              </div>
            </dl>
            <section className="feature-section">
              <div className="feature-subheading">
                <h3>Tracked population</h3>
                <span>Objects &gt; 10 cm</span>
              </div>
              <GrowthChart result={result} year={year} />
            </section>
            <div className="cascade-event-list">
              <span className="eyebrow">Secondary events</span>
              {result.secondaryCollisions.length ? (
                result.secondaryCollisions.map((collision, index) => (
                  <div key={index} className={collision.year <= year ? 'occurred' : ''}>
                    <i />
                    <span>
                      Year {collision.year.toFixed(1)}
                      <small>{collision.altKm.toFixed(0)} km altitude</small>
                    </span>
                    <b>
                      +{formatNumber(collision.fragments)}
                      <small>fragments</small>
                    </b>
                  </div>
                ))
              ) : (
                <p className="feature-footnote">No secondary collision events in this scenario.</p>
              )}
            </div>
            <p className="feature-footnote cascade-explanation">
              At year {Math.round(year)}, this breakup adds{' '}
              {formatNumber(
                Math.max(0, (current?.trackedTotal ?? 0) - (current?.baselineTotal ?? 0)),
              )}{' '}
              tracked objects above the baseline. The model illustrates why avoiding the first
              collision matters.
            </p>
          </>
        )}
      </aside>
      {result && (
        <section className="cascade-timeline feature-float" aria-label="Cascade evolution controls">
          <div className="cascade-year">
            <span className="eyebrow">Years after breakup</span>
            <strong>
              {year.toFixed(1).padStart(4, '0')}
              <small> / {activeLength}</small>
            </strong>
          </div>
          <button
            className="feature-button icon-only"
            onClick={() => {
              if (year >= activeLength) setYear(0);
              setPlaying((value) => !value);
            }}
            aria-label={playing ? 'Pause cascade evolution' : 'Play cascade evolution'}
          >
            {playing ? 'Ⅱ' : '▷'}
          </button>
          <div className="cascade-scrubber">
            <label htmlFor="cascade-year-slider" className="sr-only">
              Years after breakup
            </label>
            <input
              id="cascade-year-slider"
              type="range"
              min="0"
              max={activeLength}
              step=".05"
              value={year}
              onChange={(e) => {
                setPlaying(false);
                setYear(Number(e.target.value));
              }}
            />
            {result.secondaryCollisions.map((collision, index) => (
              <button
                key={index}
                className="cascade-event-tick"
                style={{ left: `${(collision.year / activeLength) * 100}%` }}
                onClick={() => {
                  setPlaying(false);
                  setYear(collision.year);
                }}
                aria-label={`Jump to secondary collision at year ${collision.year}`}
                title={`Secondary collision · year ${collision.year}`}
              />
            ))}
            <div className="range-endpoints">
              <span>Breakup</span>
              <span>Year {activeLength}</span>
            </div>
          </div>
        </section>
      )}
    </>
  );
}

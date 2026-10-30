import { useMemo } from 'react';
import { useCatalog } from '../../api/hooks';
import type { CascadeResult } from '../../api/types';
import { formatNumber } from '../../lib/format';
import {
  ALUMINA_2022_KG,
  ALUMINA_MEGACONSTELLATION_KG_PER_YEAR,
  RING_FORMATION_MONTHS,
  aiTimeline,
  earthImpact,
  preparednessActions,
  remainingFraction,
  satellitesInBand,
  type Persistence,
} from './earthImpact';
import './earthImpact.css';

const formatMass = (kg: number) =>
  kg < 1000 ? `${formatNumber(Math.round(kg))} kg` : `${formatNumber(Math.round(kg / 100) / 10)} t`;

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
            <b>
              {formatNumber(impact.reentriesPerYear)} reentries a year ·{' '}
              {formatMass(impact.reentryMassKgPerYear)}/yr
            </b>
            <span>
              Most burn up and leave metals in the stratosphere. About 10% of large stratospheric
              particles already contain spacecraft metals.
            </span>
          </li>
          <li>
            <b>
              ~{formatMass(impact.aluminaKg)} of aluminium oxide so far
              <small className="model-estimate"> model estimate</small>
            </b>
            <span>
              From {formatMass(impact.reenteredMassKg)} reentered, at 30 kg per 250 kg satellite.
              For scale: all reentries in 2022 made ~{formatMass(ALUMINA_2022_KG)}; planned
              mega-constellations could make ~{formatMass(ALUMINA_MEGACONSTELLATION_KG_PER_YEAR)} a
              year, with possible ozone loss (Ferreira et al., 2024).
            </span>
          </li>
          <li>
            <b>Falling debris</b>
            <span>
              Parts can survive reentry: an ISS battery-pallet part went through a Florida home (Mar
              2024, NASA confirmed) and Falcon 9 debris fell in Poland (Feb 2025).
            </span>
          </li>
          <li>
            <b>
              {impact.satellitesPossiblyLost
                ? `Up to ${impact.satellitesPossiblyLost} replacement ${impact.satellitesPossiblyLost === 1 ? 'launch' : 'launches'}`
                : 'No replacement launches yet'}
            </b>
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
      <BandSatellites altKm={impact.parentAltKm} />
      <p className="feature-footnote">
        Fragment lifetimes are fitted to the real Cosmos 1408 and Fengyun-1C clouds. Masses follow
        the simulator's assumptions and are spread evenly over each cloud's fragments. Solar minimum
        and a cooling, shrinking thermosphere both lengthen them; MIT projects low orbit could hold
        50–66% fewer satellites by 2100.
      </p>
    </div>
  );
}

function BandSatellites({ altKm }: { altKm: number }) {
  const catalog = useCatalog();
  const band = useMemo(() => satellitesInBand(catalog.data ?? [], altKm), [catalog.data, altKm]);
  if (!catalog.data) return null;
  return (
    <section className="feature-section">
      <div className="feature-subheading">
        <h3>Satellites in the debris band</h3>
        <span>From the loaded catalog</span>
      </div>
      <p className="band-count">
        <b>{formatNumber(band.activeCount)}</b> active satellites orbit within 75 km of{' '}
        {Math.round(altKm)} km.
      </p>
      {band.climate.length ? (
        <>
          <ul className="band-satellites">
            {band.climate.slice(0, 6).map((satellite) => (
              <li key={satellite.noradId}>
                <b>{satellite.name}</b>
                <span>{Math.round(satellite.altKm)} km</span>
              </li>
            ))}
          </ul>
          <p className="feature-footnote">
            Weather and climate satellites. Satellite data feed more than half of the Essential
            Climate Variables used to track climate change (ESA), so a cascade here reaches weather
            forecasts and climate records on Earth.
          </p>
        </>
      ) : null}
    </section>
  );
}

export function PreparednessPanel({ result, year }: { result: CascadeResult; year: number }) {
  const impact = earthImpact(result, year);
  const actions = preparednessActions(result, impact, year);
  const steps = aiTimeline(result, impact);
  return (
    <div className="earth-impact">
      <section className="feature-section">
        <div className="feature-subheading">
          <h3>Where AI helps</h3>
          <span>This scenario, step by step</span>
        </div>
        <ol className="ai-timeline">
          {steps.map((step) => (
            <li key={step.when + step.title} className={step.atYear <= year ? 'reached' : ''}>
              <span className="ai-when">{step.when}</span>
              <div>
                <b>{step.title}</b>
                <p>{step.detail}</p>
                <span className={`ai-by ${step.by === 'OrbitSentinel' ? 'ours' : 'research'}`}>
                  {step.by === 'OrbitSentinel' ? 'OrbitSentinel does this' : 'Published research'}
                </span>
              </div>
            </li>
          ))}
        </ol>
      </section>
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

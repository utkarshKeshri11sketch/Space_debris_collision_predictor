import { useEffect, useState, type CSSProperties } from 'react';
import type { CatalogObject, Conjunction } from '../../api/types';
import { isMockMode } from '../../api/client';
import { Icon } from '../../ui/Icon';

function CountUp({ value, digits = 0 }: { value: number; digits?: number }) {
  const [shown, setShown] = useState(() => matchMedia('(prefers-reduced-motion: reduce)').matches ? value : 0);
  useEffect(() => {
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) { setShown(value); return; }
    const start = performance.now();
    let frame = 0;
    const step = (now: number) => {
      const t = Math.min(1, (now - start) / 650);
      setShown(value * (1 - (1 - t) ** 3));
      if (t < 1) frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [value]);
  return <>{shown.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })}</>;
}

export default function ObjectInspector({
  object,
  nextApproach,
  onClose,
  onFocus,
  onViewConjunctions,
}: {
  object: CatalogObject;
  nextApproach?: Conjunction;
  onClose: () => void;
  onFocus: () => void;
  onViewConjunctions: (id: string) => void;
}) {
  const motion = Number(object.omm.MEAN_MOTION);
  const semiMajor = Math.cbrt(398600.4418 / ((motion * 2 * Math.PI) / 86400) ** 2);
  const eccentricity = Number(object.omm.ECCENTRICITY);
  const altitude = semiMajor - 6378.137;
  const inclination = Number(object.omm.INCLINATION);
  const phase = (Number(object.omm.MEAN_ANOMALY) * Math.PI) / 180;
  const type =
    object.type === 'PAYLOAD'
      ? 'Satellite'
      : object.type === 'ROCKET_BODY'
        ? 'Rocket body'
        : object.type === 'DEBRIS'
          ? 'Debris'
          : 'Unclassified';
  const color =
    object.type === 'PAYLOAD'
      ? 'var(--sat)'
      : object.type === 'DEBRIS'
        ? 'var(--debris)'
        : 'var(--rocket)';
  const epoch = String(object.omm.EPOCH ?? 'Unavailable');
  const epochDate = Date.parse(epoch.endsWith('Z') ? epoch : `${epoch}Z`);
  const perigee = semiMajor * (1 - eccentricity) - 6378.137;
  const apogee = semiMajor * (1 + eccentricity) - 6378.137;
  const operator = String(object.omm.OWNER ?? object.omm.OPERATOR ?? object.omm.COUNTRY_CODE ?? object.omm.COUNTRY ?? 'Not published');
  return (
    <aside
      className="object-inspector"
      aria-label="Selected object details"
      style={{ '--object-color': color } as CSSProperties}
    >
      <header className="inspector-header">
        <span>
          Catalog <span>/</span> Object inspector
        </span>
        <button className="icon-button" aria-label="Close object details" onClick={onClose}>
          <Icon name="close" size={17} />
        </button>
      </header>
      <div className="inspector-scroll">
        <div className="inspector-identity">
          <div className="inspector-class">
            <i />
            {type}
            <span>{object.active ? 'Active' : 'Inactive'}</span>
          </div>
          <h2>{object.name}</h2>
          <span className="inspector-id">
            NORAD <b>{object.noradId}</b>
          </span>
        </div>
        <div className="inspector-altitude">
          <span>Mean orbital altitude</span>
          <strong>
            <CountUp key={object.noradId} value={altitude} />
            <small>km</small>
          </strong>
          <div className="altitude-range">
            <span>
              Perigee <b>{perigee.toFixed(0)} km</b>
            </span>
            <span>
              Apogee <b>{apogee.toFixed(0)} km</b>
            </span>
          </div>
        </div>
        <div className="inspector-metrics">
          <div>
            <span>
              Orbital speed <small>≈</small>
            </span>
            <strong>
              <CountUp key={object.noradId} value={Math.sqrt(398600.4418 / semiMajor)} digits={2} />
              <small>km/s</small>
            </strong>
          </div>
          <div>
            <span>Orbital period</span>
            <strong>
              {(1440 / motion).toFixed(1)}
              <small>min</small>
            </strong>
          </div>
          <div>
            <span>Inclination</span>
            <strong>
              <CountUp key={object.noradId} value={inclination} digits={2} />
              <small>°</small>
            </strong>
          </div>
          <div>
            <span>Eccentricity</span>
            <strong>{eccentricity.toFixed(4)}</strong>
          </div>
        </div>
        <div className="inspector-orbit">
          <div className="inspector-section-label">
            Orbital geometry<span>Mean elements</span>
          </div>
          <svg
            viewBox="0 0 280 126"
            role="img"
            aria-label={`Illustrative orbital plane at ${inclination.toFixed(1)} degrees inclination`}
          >
            <defs>
              <pattern id="orbit-grid" width="20" height="20" patternUnits="userSpaceOnUse">
                <path d="M20 0H0V20" fill="none" stroke="#28313b" strokeWidth=".5" />
              </pattern>
            </defs>
            <rect width="280" height="126" fill="url(#orbit-grid)" />
            <path d="M25 63H255" stroke="#424a55" strokeWidth=".8" strokeDasharray="3 5" />
            <circle cx="140" cy="63" r="24" fill="#141e28" stroke="#536578" strokeWidth=".8" />
            <path
              d="M116 63h48m-24-24c-15 17-15 31 0 48 15-17 15-31 0-48"
              stroke="#536578"
              strokeWidth=".6"
              fill="none"
            />
            <g transform={`rotate(${-Math.min(inclination, 165) * 0.35} 140 63)`}>
              <ellipse
                cx="140"
                cy="63"
                rx="99"
                ry="27"
                fill="none"
                stroke="var(--object-color)"
                strokeOpacity=".65"
                strokeWidth="1"
              />
              <circle
                cx={140 + 99 * Math.cos(phase)}
                cy={63 + 27 * Math.sin(phase)}
                r="3.5"
                fill="var(--object-color)"
                stroke="#0d1118"
                strokeWidth="1.5"
              />
            </g>
            <text x="12" y="115" fill="#9099a8" fontSize="9">
              Earth equatorial plane
            </text>
            <text x="267" y="115" textAnchor="end" fill="#c1c7d1" fontSize="10">
              {inclination.toFixed(1)}°
            </text>
          </svg>
        </div>
        <dl className="inspector-record">
          <div><dt>Operator / country</dt><dd>{operator}</dd></div>
          <div><dt>Next close approach</dt><dd>{nextApproach ? <><time dateTime={nextApproach.tca}>{new Date(nextApproach.tca).toLocaleString('en-US', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'UTC' })} UTC</time><small>{nextApproach.missDistanceM.toLocaleString('en-US')} m miss</small></> : 'None in screening window'}</dd></div>
          <div>
            <dt>Orbit regime</dt>
            <dd>
              {altitude < 2000
                ? 'Low Earth orbit'
                : altitude > 35000
                  ? 'Geosynchronous'
                  : 'Medium Earth orbit'}
            </dd>
          </div>
          <div>
            <dt>Maneuver capability</dt>
            <dd className={object.maneuverable ? 'capable' : ''}>
              {object.maneuverable ? 'Available' : 'Not maneuverable'}
            </dd>
          </div>
          <div>
            <dt>Element epoch</dt>
            <dd>
              {Number.isFinite(epochDate)
                ? new Date(epochDate).toISOString().replace('T', ' · ').slice(0, 21)
                : 'Unavailable'}
              <small>UTC</small>
            </dd>
          </div>
        </dl>
        <button className="inspector-focus" onClick={onFocus}>
          <Icon name="target" size={16} />
          Focus on object<span>F</span>
          <Icon name="arrow" size={16} />
        </button>
        <button className="inspector-conjunction" onClick={() => nextApproach && onViewConjunctions(nextApproach.id)} disabled={!nextApproach}>
          <Icon name="alert" size={16} />
          {nextApproach ? 'View conjunctions' : 'No screened conjunctions'}
          <Icon name="arrow" size={16} />
        </button>
        <p className="inspector-provenance">
          {isMockMode ? 'Synthetic catalog · Sample data' : 'Backend orbit catalog'}
          <span>SGP4 · OMM · WGS-72</span>
        </p>
      </div>
    </aside>
  );
}

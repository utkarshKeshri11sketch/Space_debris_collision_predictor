import { useEffect, useRef, useState } from 'react';
import Ticker from '../../ui/Ticker';
import { useNavigate } from 'react-router-dom';
import { useConjunction } from '../../api/hooks';
import { isMockMode } from '../../api/client';
import type { ConjunctionDetail, ManeuverOption } from '../../api/types';
import { useSimStore } from '../../sim/clock';
import {
  formatCountdown,
  formatDistance,
  formatProbability,
  formatPropellant,
  formatUtc,
  probabilityOdds,
} from '../../lib/format';

interface Props {
  id: string;
  onReplay: (progress: number) => void;
  onPreviewBurn: (value: boolean) => void;
  onNegotiate: (conjunctionId: string) => void;
}

function RangeChart({ data, option }: { data: ConjunctionDetail; option?: ManeuverOption }) {
  const series = data.rangeSeries.filter((p) => Math.abs(p.tSec) <= 60);
  const points = series.length ? series : data.rangeSeries;
  const span = Math.max(60, ...points.map((p) => Math.abs(p.tSec)));
  const max = Math.max(1000, ...points.map((p) => p.rangeKm));
  const x = (time: number) => 40 + ((time + span) / (2 * span)) * 276;
  const y = (range: number) =>
    144 - ((Math.log10(Math.max(0.1, range)) + 1) / (Math.log10(max) + 1)) * 124;
  const line = points.map((p) => `${x(p.tSec)},${y(p.rangeKm)}`).join(' ');
  const proposedSeries =
    option?.recommended && data.afterSeries?.length
      ? data.afterSeries.filter((point) => Math.abs(point.tSec) <= span)
      : points.map((point) => ({
          tSec: point.tSec,
          rangeKm: Math.hypot(
            point.tSec * data.relSpeedKms,
            (option?.newMissM ?? data.missDistanceM) / 1000,
          ),
        }));
  const predicted = proposedSeries.map((point) => `${x(point.tSec)},${y(point.rangeKm)}`).join(' ');
  return (
    <div className="feature-chart">
      <svg
        viewBox="0 0 340 184"
        role="img"
        aria-label="Range versus time around closest approach, logarithmic kilometres"
      >
        {[1, 10, 100, 1000].map((value) => (
          <g key={value}>
            <line
              x1="40"
              x2="316"
              y1={y(value)}
              y2={y(value)}
              className={value === 1 ? 'chart-threshold' : 'chart-grid'}
            />
            <text x="32" y={y(value) + 4} textAnchor="end">
              {value}
            </text>
          </g>
        ))}
        <line x1={x(0)} x2={x(0)} y1="16" y2="148" className="chart-grid" strokeDasharray="2 4" />
        <polyline points={line} className="chart-line chart-line-orange" />
        {option?.direction !== 'none' && option && (
          <polyline
            points={predicted}
            className="chart-line chart-line-cyan"
            strokeDasharray="4 3"
          />
        )}
        <circle cx={x(0)} cy={y(data.missDistanceM / 1000)} r="3" fill="var(--debris)" />
        <text x="40" y="166">
          −{span} s
        </text>
        <text x={x(0)} y="166" textAnchor="middle">
          TCA
        </text>
        <text x="316" y="166" textAnchor="end">
          +{span} s
        </text>
      </svg>
      <div className="chart-legend">
        <span>
          <i className="legend-line orange" />
          Current path
        </span>
        {option && option.direction !== 'none' && (
          <span>
            <i className="legend-line cyan" />
            Option {option.label}
          </span>
        )}
        <span className="chart-caption">Range · km · log scale</span>
      </div>
    </div>
  );
}

function EncounterPlane({ data }: { data: ConjunctionDetail }) {
  const { sigmaMajorM, sigmaMinorM, angleDeg } = data.covariance;
  const extent = Math.max(
    3 * sigmaMajorM + Math.abs(data.rtnM.r),
    3 * sigmaMinorM + Math.abs(data.rtnM.n),
    data.missDistanceM,
    100,
  );
  const scale = 110 / extent;
  const cx = 150 + data.rtnM.r * scale;
  const cy = 92 - data.rtnM.n * scale;
  return (
    <svg
      className="encounter-plane"
      viewBox="0 0 300 186"
      role="img"
      aria-label="Encounter plane showing relative miss point, one and three sigma position uncertainty, and combined hard-body radius"
    >
      <line x1="15" x2="286" y1="92" y2="92" className="chart-grid" />
      <line x1="150" x2="150" y1="12" y2="174" className="chart-grid" />
      <g transform={`rotate(${-angleDeg} ${cx} ${cy})`}>
        <ellipse
          cx={cx}
          cy={cy}
          rx={Math.max(2, sigmaMajorM * scale * 3)}
          ry={Math.max(2, sigmaMinorM * scale * 3)}
          className="uncertainty-outer"
        />
        <ellipse
          cx={cx}
          cy={cy}
          rx={Math.max(1, sigmaMajorM * scale)}
          ry={Math.max(1, sigmaMinorM * scale)}
          className="uncertainty-inner"
        />
      </g>
      <line x1="150" y1="92" x2={cx} y2={cy} stroke="var(--text-3)" strokeDasharray="3 4" />
      <circle cx="150" cy="92" r={Math.max(3, data.hardBodyRadiusM * scale)} fill="var(--sat)" />
      <circle cx={cx} cy={cy} r="3.5" fill="var(--debris)" />
      <text x="17" y="20">
        N
      </text>
      <text x="274" y="83">
        R
      </text>
      <text x="17" y="172">
        3σ uncertainty
      </text>
      <text x="283" y="172" textAnchor="end">
        HBR {data.hardBodyRadiusM} m
      </text>
    </svg>
  );
}

export default function ConjunctionScreen({ id, onReplay, onPreviewBurn, onNegotiate }: Props) {
  const navigate = useNavigate();
  const query = useConjunction(id);
  const timeMs = useSimStore((s) => s.timeMs);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [replaying, setReplaying] = useState(false);
  const [progress, setProgress] = useState(0.5);
  const raf = useRef(0);
  const replayCallback = useRef(onReplay);
  const previewCallback = useRef(onPreviewBurn);
  replayCallback.current = onReplay;
  previewCallback.current = onPreviewBurn;
  const data = query.data;
  useEffect(() => {
    setSelectedId(null);
    setProgress(0.5);
    setReplaying(false);
    previewCallback.current(false);
    replayCallback.current(0.5);
    return () => cancelAnimationFrame(raf.current);
  }, [id]);
  const selected = data?.options.find((o) => o.id === selectedId);
  const chooseOption = (option: ManeuverOption) => {
    setSelectedId(option.id);
    onPreviewBurn(option.direction !== 'none');
  };
  const replay = () => {
    cancelAnimationFrame(raf.current);
    setReplaying(true);
    const start = performance.now();
    const step = (now: number) => {
      const next = Math.min(1, (now - start) / 12000);
      setProgress(next);
      replayCallback.current(next);
      if (next < 1) raf.current = requestAnimationFrame(step);
      else {
        setReplaying(false);
        setProgress(0.5);
        replayCallback.current(0.5);
      }
    };
    raf.current = requestAnimationFrame(step);
  };
  if (query.isPending)
    return (
      <aside className="route-panel route-panel-left feature-state" aria-busy="true">
        <span className="eyebrow">Encounter analysis</span>
        <h2>Resolving orbital geometry</h2>
        <p>Loading covariance, relative paths and maneuver options.</p>
        <div className="feature-skeleton" />
        <div className="feature-skeleton short" />
      </aside>
    );
  if (query.isError || !data)
    return (
      <aside className="route-panel route-panel-left feature-state">
        <span className="eyebrow">Encounter unavailable</span>
        <h2>Analysis could not load</h2>
        <p>{query.error?.message ?? 'This encounter is not in the latest screening run.'}</p>
        <button className="feature-button" onClick={() => void query.refetch()}>
          Retry analysis
        </button>
      </aside>
    );
  const tSec = (progress - 0.5) * 120;
  const currentRange = Math.hypot(tSec * data.relSpeedKms * 1000, data.missDistanceM);
  const recommended = data.options.find((o) => o.recommended);
  return (
    <>
      <aside className="route-panel route-panel-left feature-panel encounter-summary">
        <header className="feature-panel-heading">
          <span className="eyebrow">Conjunction analysis</span>
          <span className={`feature-risk ${data.risk}`}>{data.risk}</span>
        </header>
        <h2 className="feature-title">Encounter parameters</h2>
        <div className="object-pair">
          <div>
            <i className="object-dot satellite" />
            <span>
              {data.primary.name}
              <small>NORAD {data.primary.noradId} · Primary</small>
            </span>
          </div>
          <div>
            <i className="object-dot debris" />
            <span>
              {data.secondary.name}
              <small>NORAD {data.secondary.noradId} · Secondary</small>
            </span>
          </div>
        </div>
        <div className="feature-countdown">
          <span className="eyebrow">Time to closest approach</span>
          <strong>{formatCountdown(data.tca, timeMs)}</strong>
          <small>{formatUtc(data.tca)}</small>
        </div>
        <dl className="encounter-metrics">
          <div>
            <dt>Predicted miss</dt>
            <dd><Ticker value={data.missDistanceM} format={formatDistance} /></dd>
          </div>
          <div>
            <dt>Collision probability</dt>
            <dd>
              {formatProbability(data.pc)}
              <small>{probabilityOdds(data.pc)}</small>
              {!isMockMode && (
                // Backend default SCREENING_PC_MODEL=max: public orbit data has no covariance.
                <span
                  className="pc-bound"
                  title="Public orbit data carries no error estimates, so this is the highest probability any error size could give (maximum-probability bound), not a guess."
                >
                  worst-case bound
                </span>
              )}
            </dd>
          </div>
          <div>
            <dt>Relative velocity</dt>
            <dd>
              {data.relSpeedKms.toFixed(1)} <small className="inline-unit">km/s</small>
            </dd>
          </div>
        </dl>
        <div className="rtn-split">
          <span>
            R <b>{data.rtnM.r.toFixed(0)} m</b>
          </span>
          <span>
            T <b>{data.rtnM.t.toFixed(0)} m</b>
          </span>
          <span>
            N <b>{data.rtnM.n.toFixed(0)} m</b>
          </span>
        </div>
        <section className="feature-section">
          <div className="feature-subheading">
            <h3>Encounter plane</h3>
            <span>1σ / 3σ</span>
          </div>
          <EncounterPlane data={data} />
          <p className="feature-footnote">
            Combined uncertainty at closest approach. The solid point is the primary object.
          </p>
        </section>
      </aside>
      <div className="encounter-replay feature-float">
        <div>
          <span className="eyebrow">Encounter replay</span>
          <strong>
            {replaying
              ? `T${tSec < 0 ? '−' : '+'}${Math.abs(tSec).toFixed(0).padStart(2, '0')} s`
              : 'Closest approach'}
          </strong>
          <small>
            Separation <b>{formatDistance(currentRange)}</b>
          </small>
        </div>
        <button className="feature-button" onClick={replay} disabled={replaying}>
          {replaying ? 'Replaying…' : '↻ Replay encounter'}
        </button>
      </div>
      <aside className="route-panel route-panel-right feature-panel avoidance-panel">
        <header className="feature-panel-heading">
          <span className="eyebrow">Avoidance planning</span>
          <span className="feature-status">Operator review</span>
        </header>
        <h2 className="feature-title">Avoidance plan</h2>
        <p className="feature-description">
          Select a maneuver to compare separation and propellant cost.
        </p>
        <section className="feature-section">
          <div className="feature-subheading">
            <h3>Range at encounter</h3>
            <span>Alert &lt; 1 km</span>
          </div>
          <RangeChart data={data} option={selected} />
        </section>
        <div className="feature-subheading">
          <h3>Maneuver options</h3>
          <span>Select to preview</span>
        </div>
        {data.options.length ? (
          <div className="maneuver-options">
            {data.options.map((option) => (
              <button
                key={option.id}
                className={`maneuver-option ${selectedId === option.id ? 'selected' : ''}`}
                onClick={() => chooseOption(option)}
                aria-pressed={selectedId === option.id}
              >
                <div className="maneuver-option-title">
                  <strong>
                    {option.label === 'No action'
                      ? 'No action'
                      : `Option ${option.label} · ${option.direction}`}
                  </strong>
                  {option.recommended && <span>Recommended</span>}
                </div>
                <dl>
                  <div>
                    <dt>Δv</dt>
                    <dd>
                      {option.dvMs.toFixed(2)} <small>m/s</small>
                    </dd>
                  </div>
                  <div>
                    <dt>New miss</dt>
                    <dd>{formatDistance(option.newMissM)}</dd>
                  </div>
                  <div>
                    <dt>Fuel</dt>
                    <dd>{formatPropellant(option.propellantKg)}</dd>
                  </div>
                </dl>
              </button>
            ))}
          </div>
        ) : (
          <p className="feature-empty">
            No viable avoidance burns were returned for this encounter.
          </p>
        )}
        {selected && (
          <div className="burn-preview-note" role="status">
            <span className="eyebrow">
              Preview ·{' '}
              {selected.direction === 'none' ? 'Current trajectory' : 'Proposed trajectory'}
            </span>
            <p>
              {selected.burnAt
                ? `Burn at ${formatUtc(selected.burnAt)}.`
                : 'Maintain the current orbit.'}{' '}
              Collision probability: {formatProbability(selected.newPc)}.
            </p>
          </div>
        )}
        {!data.secondary.maneuverable ? (
          <p className="nonmaneuverable">
            <span className="status-square" />
            {data.secondary.name} cannot maneuver. The primary operator must act.
          </p>
        ) : (
          <button
            className="feature-button primary full-width"
            onClick={() => onNegotiate(data.id)}
          >
            Start operator negotiation <span aria-hidden="true">↗</span>
          </button>
        )}
        <button
          className="feature-button full-width what-if-button"
          onClick={() =>
            navigate(`/cascade?norad=${data.primary.noradId}&from=${encodeURIComponent(data.id)}`)
          }
        >
          What if this one hits? <span aria-hidden="true">→ Cascade Lab</span>
        </button>
        <section className="feature-section feature-brief">
          <span className="eyebrow">Sentinel assessment</span>
          <p>{data.brief}</p>
          <small>
            {isMockMode
              ? 'Sample briefing · simulated AI assessment'
              : 'AI assessment from the screening run'}
          </small>
          {recommended && (
            <small>
              Recommended burn: {recommended.dvMs.toFixed(2)} m/s {recommended.direction}. Human
              approval required.
            </small>
          )}
        </section>
      </aside>
    </>
  );
}

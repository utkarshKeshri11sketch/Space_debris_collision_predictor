import { useEffect, useRef, useState } from 'react';
import { api } from '../../api/client';
import { useCaseStudies, useCaseStudy } from '../../api/hooks';
import type { CaseStudy, NegotiationEvent } from '../../api/types';
import { formatDistance, formatProbability, formatPropellant } from '../../lib/format';
import { knownValues } from '../../lib/grounding';
import { PhysicsText } from '../../ui/PhysicsText';
import './caseStudy.css';

export { formatPropellant };

type Message = Extract<NegotiationEvent, { type: 'message' }>;
type Scores = Extract<NegotiationEvent, { type: 'scores' }>;
type Agreement = Extract<NegotiationEvent, { type: 'agreement' }>;
type View = 'reality' | 'sentinel';

interface Props {
  caseId?: string;
  onSelect: (id: string) => void;
}

/** Log-scale bar width between 0.1 g and 1 kg, so a 400x gap is still visible. */
export function propellantBar(kg: number): number {
  const lo = Math.log10(1e-4);
  const hi = Math.log10(1);
  return Math.max(3, Math.min(100, ((Math.log10(Math.max(kg, 1e-6)) - lo) / (hi - lo)) * 100));
}

const tonnes = (kg: number) =>
  kg >= 1000 ? `${(kg / 1000).toFixed(kg >= 10000 ? 0 : 1)} t` : `${kg.toFixed(0)} kg`;
const longDate = (iso: string) =>
  new Date(`${iso}T00:00:00Z`).toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  });

function EncounterDiagram({ data, view }: { data: CaseStudy; view: View }) {
  const conj = data.conjunction!;
  const station = conj.primary;
  const starlink = conj.secondary;
  const stationMoves = view === 'reality' || data.orbitSentinel?.moverSide === 'a';
  const stationPath = 'M 40 190 Q 300 112 560 34';
  const starlinkPath = 'M 40 34 Q 300 112 560 190';
  const stationDodge = 'M 40 190 Q 250 40 560 6';
  const starlinkDodge = 'M 40 34 Q 330 40 560 150';
  const reduceMotion =
    typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
  return (
    <svg
      className="cs-diagram"
      viewBox="0 0 600 224"
      role="img"
      aria-label={`${stationMoves ? station.name : starlink.name} changes orbit to avoid a ${formatDistance(conj.missDistanceM)} approach`}
    >
      <path className="cs-orbit cs-orbit-station" d={stationPath} />
      <path className="cs-orbit cs-orbit-starlink" d={starlinkPath} />
      <path key={view} className="cs-dodge" d={stationMoves ? stationDodge : starlinkDodge} />
      <circle className="cs-crossing" cx="300" cy="112" r="14" />
      <text className="cs-crossing-label" x="318" y="132">
        {formatDistance(conj.missDistanceM)} · {conj.relSpeedKms.toFixed(1)} km/s
      </text>
      {reduceMotion ? (
        <>
          <circle
            className="cs-body cs-body-station"
            r="9"
            cx={stationMoves ? 232 : 236}
            cy={stationMoves ? 82 : 128}
          />
          <circle
            className="cs-body cs-body-starlink"
            r="3.5"
            cx={stationMoves ? 236 : 236}
            cy={stationMoves ? 96 : 66}
          />
        </>
      ) : (
        <>
          <circle className="cs-body cs-body-station" r="9">
            <animateMotion
              key={`a-${view}`}
              dur="7s"
              repeatCount="indefinite"
              path={stationMoves ? stationDodge : stationPath}
            />
          </circle>
          <circle className="cs-body cs-body-starlink" r="3.5">
            <animateMotion
              key={`b-${view}`}
              dur="7s"
              repeatCount="indefinite"
              path={stationMoves ? starlinkPath : starlinkDodge}
            />
          </circle>
        </>
      )}
      <text className="cs-label" x="44" y="214">
        {station.name}
        {data.reality ? ` · ${tonnes(data.reality.massKg)}` : ''} · crewed
      </text>
      <text className="cs-label" x="44" y="22">
        {starlink.name}
        {data.orbitSentinel?.moverSide === 'b'
          ? ` · ${tonnes(data.orbitSentinel.moverMassKg)}`
          : ''}{' '}
        · uncrewed
      </text>
      <text className="cs-mover" x="590" y="214" textAnchor="end">
        {stationMoves ? `${station.name} burns` : `${starlink.name} burns`}
      </text>
    </svg>
  );
}

function RealityTimeline({ data }: { data: CaseStudy }) {
  const source = (key: string) => data.sources.find((s) => s.key === key);
  const rows = [...data.facts.map((f) => ({ date: data.date, ...f })), ...data.aftermath];
  return (
    <section className="cs-column cs-reality">
      <span className="eyebrow">{data.date.slice(0, 4)} · Without a negotiator</span>
      <h3>What happened</h3>
      <ol className="cs-timeline">
        {rows.map((row, i) => {
          const s = source(row.source);
          return (
            <li key={i}>
              <time>{longDate(row.date)}</time>
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
      <div className="cs-verdict cs-verdict-bad">Agreement on who should move: never reached</div>
    </section>
  );
}

function SentinelReplay({
  data,
  onMeasured,
}: {
  data: CaseStudy;
  onMeasured: (seconds: number) => void;
}) {
  // Messages and scores in stream order, so the score table appears where the mediator used it.
  const [events, setEvents] = useState<(Message | Scores)[]>([]);
  const [agreement, setAgreement] = useState<Agreement | null>(null);
  const [status, setStatus] = useState<'idle' | 'streaming' | 'complete' | 'error'>('idle');
  const [error, setError] = useState('');
  const [elapsed, setElapsed] = useState(0);
  const controller = useRef<AbortController | null>(null);
  const list = useRef<HTMLOListElement>(null);
  const name = (speaker: Message['speaker']) =>
    speaker === 'mediator'
      ? 'Sentinel mediator'
      : `${(speaker === 'agentA' ? data.conjunction?.primary : data.conjunction?.secondary)?.name} agent`;

  useEffect(() => () => controller.current?.abort(), []);
  useEffect(() => {
    if (list.current) list.current.scrollTop = list.current.scrollHeight;
  }, [events, agreement]);

  const run = async () => {
    controller.current?.abort();
    const abort = new AbortController();
    controller.current = abort;
    setEvents([]);
    setAgreement(null);
    setError('');
    setStatus('streaming');
    const started = performance.now();
    const tick = window.setInterval(() => setElapsed((performance.now() - started) / 1000), 100);
    try {
      const { negotiationId } = await api.startNegotiation(data.id, abort.signal);
      await api.streamNegotiation(
        negotiationId,
        (event) => {
          if (event.type === 'message' || event.type === 'scores')
            setEvents((items) => [...items, event]);
          if (event.type === 'agreement') {
            onMeasured((performance.now() - started) / 1000);
            setAgreement(event);
            setStatus('complete');
          }
          if (event.type === 'error') {
            setError(event.message);
            setStatus('error');
          }
        },
        abort.signal,
      );
      setStatus((s) => (s === 'streaming' ? 'error' : s));
    } catch (cause) {
      if (!abort.signal.aborted) {
        setError(cause instanceof Error ? cause.message : 'The negotiation could not be replayed.');
        setStatus('error');
      }
    } finally {
      window.clearInterval(tick);
      setElapsed((performance.now() - started) / 1000);
    }
  };

  return (
    <section className="cs-column cs-sentinel">
      <span className="eyebrow">With OrbitSentinel · live replay</span>
      <h3>Negotiated in seconds</h3>
      {status === 'idle' ? (
        <div className="cs-replay-start">
          <p>
            Both operators&apos; agents argue their case and the mediator scores who should move, on
            the reconstructed event.
          </p>
          <button className="feature-button primary" onClick={() => void run()}>
            Replay the negotiation
          </button>
        </div>
      ) : (
        <ol className="cs-transcript" ref={list} aria-live="polite">
          {events.map((item, i) =>
            item.type === 'message' ? (
              <li key={i} className={`cs-msg cs-msg-${item.speaker}`}>
                <b>{name(item.speaker)}</b>
                <PhysicsText
                  text={item.text}
                  known={
                    data.conjunction
                      ? knownValues(data.conjunction, agreement ? [agreement] : [])
                      : []
                  }
                />
              </li>
            ) : (
              <li key={i} className="cs-scores">
                <b>Mediator scores (35 / 25 / 20 / 20)</b>
                <table>
                  <thead>
                    <tr>
                      <th />
                      <th>{data.conjunction?.primary.name} moves</th>
                      <th>{data.conjunction?.secondary.name} moves</th>
                    </tr>
                  </thead>
                  <tbody>
                    {item.criteria.map((c) => (
                      <tr key={c.name}>
                        <td>{c.name}</td>
                        <td>{Math.round(c.a)}</td>
                        <td>{Math.round(c.b)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </li>
            ),
          )}
          {agreement && (
            <li className="cs-agreement">
              <b>Agreement · {agreement.mover.name} moves</b>
              <p>
                {agreement.maneuver.dvMs.toFixed(2)} m/s {agreement.maneuver.direction},{' '}
                {formatPropellant(agreement.maneuver.propellantKg)},{' '}
                {formatDistance(agreement.maneuver.newMissM)} separation. Signed by{' '}
                {agreement.signedBy.join(', ')}; a human operator approves before any command.
              </p>
            </li>
          )}
          {status === 'error' && (
            <li className="cs-error">{error || 'The stream ended before an agreement.'}</li>
          )}
        </ol>
      )}
      <div className={`cs-verdict ${status === 'complete' ? 'cs-verdict-good' : ''}`}>
        {status === 'complete' ? (
          `Agreement on who should move: ${elapsed.toFixed(1)} s (measured in this replay)`
        ) : status === 'streaming' ? (
          `Negotiating… ${elapsed.toFixed(1)} s`
        ) : status === 'error' ? (
          <button className="feature-button" onClick={() => void run()}>
            Retry replay
          </button>
        ) : (
          'Agreement on who should move: replay to measure'
        )}
      </div>
    </section>
  );
}

function Comparison({ data }: { data: CaseStudy }) {
  const reality = data.reality!;
  const decision = data.orbitSentinel!;
  const conj = data.conjunction!;
  const mover = decision.moverSide === 'a' ? conj.primary : conj.secondary;
  const ratio = data.comparison?.propellantRatio;
  return (
    <section className="cs-compare" aria-label="Comparison">
      <div className="cs-compare-head">
        <span />
        <span>{data.date.slice(0, 4)} reality</span>
        <span>With OrbitSentinel</span>
      </div>
      <div className="cs-row">
        <span>Who moved</span>
        <span>
          {conj.primary.name} · {tonnes(reality.massKg)} · crewed
        </span>
        <span className="good">
          {mover.name} · {tonnes(decision.moverMassKg)} ·{' '}
          {decision.moverSide === 'a' ? 'crewed' : 'uncrewed'}
        </span>
      </div>
      <div className="cs-row cs-row-bars">
        <span>
          Propellant <small>log scale</small>
        </span>
        <span>
          <i className="cs-bar bad" style={{ width: `${propellantBar(reality.propellantKg)}%` }} />
          {formatPropellant(reality.propellantKg)}
          <small className="cs-cell-note">cheapest safe station burn (lower bound)</small>
        </span>
        <span>
          <i
            className="cs-bar good"
            style={{ width: `${propellantBar(decision.maneuver.propellantKg)}%` }}
          />
          {formatPropellant(decision.maneuver.propellantKg)}
          {ratio && <b className="cs-ratio">{Math.round(ratio)}× less</b>}
        </span>
      </div>
      <div className="cs-row">
        <span>Delta-v</span>
        <span>{reality.dvMs !== null ? `${reality.dvMs.toFixed(2)} m/s` : 'not published'}</span>
        <span>
          {decision.maneuver.dvMs.toFixed(2)} m/s {decision.maneuver.direction}
        </span>
      </div>
      <div className="cs-row">
        <span>After the burn</span>
        <span>Station flew the avoidance with crew aboard</span>
        <span className="good">
          {formatDistance(decision.maneuver.newMissM)} miss, Pc{' '}
          {formatProbability(decision.maneuver.newPc)}
        </span>
      </div>
      <div className="cs-row">
        <span>Coordination</span>
        <span>None; a UN note months later</span>
        <span className="good">Both agents sign; humans approve</span>
      </div>
    </section>
  );
}

/** The headline contrast, readable from the back of the room. */
function RewindBanner({ data, seconds }: { data: CaseStudy; seconds: number | null }) {
  const ratio = data.comparison?.propellantRatio;
  return (
    <div className="cs-rewind" aria-label="Headline comparison">
      <div className="cs-rewind-side bad">
        <span>{data.date.slice(0, 4)} · without a negotiator</span>
        <strong>Agreement never reached</strong>
        <small>The crewed station moved alone; China notified the UN months later.</small>
      </div>
      <div className="cs-rewind-side good">
        <span>With OrbitSentinel</span>
        <strong>
          {seconds !== null ? `Agreement in ${seconds.toFixed(1)} s` : 'Agreement in seconds'}
        </strong>
        <small>
          {ratio ? `${Math.round(ratio)}× less propellant` : 'Both sides costed'}
          {seconds === null ? ' · replay below to measure the time' : ' · measured in this replay'}
        </small>
      </div>
    </div>
  );
}

export default function CaseStudyScreen({ caseId, onSelect }: Props) {
  const list = useCaseStudies();
  const id = caseId ?? list.data?.[0]?.id;
  const query = useCaseStudy(id);
  const [view, setView] = useState<View>('reality');
  const [measured, setMeasured] = useState<number | null>(null);
  useEffect(() => setMeasured(null), [id]);
  const data = query.data;
  const ready = data && data.conjunction && data.reality && data.orbitSentinel;

  return (
    <div className="case-study" aria-busy={query.isPending}>
      <header className="cs-header">
        <div>
          <span className="eyebrow">Rewind · a real incident replayed through OrbitSentinel</span>
          <h2>{data?.title ?? 'Loading case study…'}</h2>
        </div>
        <div className="cs-tabs" role="tablist" aria-label="Incident">
          {list.data?.map((c) => (
            <button
              key={c.id}
              role="tab"
              aria-selected={c.id === id}
              className={c.id === id ? 'active' : ''}
              onClick={() => onSelect(c.id)}
            >
              {longDate(c.date)}
            </button>
          ))}
        </div>
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
      {data && !ready && (
        <div className="feature-state">
          <h3>Reconstruction in progress</h3>
          <p>
            Physics: {data.status.physics} · Decision: {data.status.ai}. Numbers appear once each
            part is delivered; nothing is estimated in the meantime.
          </p>
        </div>
      )}
      {ready && (
        <>
          <RewindBanner data={data} seconds={measured} />
          <div className="cs-stage">
            <div className="cs-toggle" role="radiogroup" aria-label="Scenario">
              <button
                role="radio"
                aria-checked={view === 'reality'}
                className={view === 'reality' ? 'active bad' : ''}
                onClick={() => setView('reality')}
              >
                {data.date.slice(0, 4)}: what happened
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
            <EncounterDiagram data={data} view={view} />
            {data.narrative && (
              <p className="cs-brief">
                {view === 'reality' ? data.narrative.reality : data.narrative.orbitSentinel}
              </p>
            )}
          </div>
          <div className="cs-columns">
            <RealityTimeline data={data} />
            <SentinelReplay key={data.id} data={data} onMeasured={setMeasured} />
          </div>
          <Comparison data={data} />
          <footer className="cs-footnote">
            Reconstructed from published orbits (UN note A/AC.105/1262); the real time of closest
            approach, miss distance and burn sizes were never published. The station&apos;s burn is
            modelled as the cheapest safe burn, so the gap shown is a lower bound.
            <details>
              <summary>All modelling assumptions ({data.assumptions.length})</summary>
              <ul>
                {data.assumptions.map((a, i) => (
                  <li key={i}>{a}</li>
                ))}
              </ul>
            </details>
          </footer>
        </>
      )}
    </div>
  );
}

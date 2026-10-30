import { useEffect, useRef, useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { api, isMockMode } from '../../api/client';
import { useConjunction } from '../../api/hooks';
import type { NegotiationEvent } from '../../api/types';
import { formatDistance, formatProbability, formatPropellant, formatUtc } from '../../lib/format';
import { ScoreFill, SignedStamp } from '../../ui/DemoMotion';
import { knownValues } from '../../lib/grounding';
import { PhysicsText } from '../../ui/PhysicsText';
import { WeightExplorer } from './WeightExplorer';

type Message = Extract<NegotiationEvent, { type: 'message' }>;
type Scores = Extract<NegotiationEvent, { type: 'scores' }>;
type Agreement = Extract<NegotiationEvent, { type: 'agreement' }>;
interface Props {
  conjunctionId: string;
  onAgreement?: (event: Agreement) => void;
}

function OperatorCard({
  name,
  noradId,
  side,
  active,
  agreed,
}: {
  name: string;
  noradId: number;
  side: 'a' | 'b';
  active: boolean;
  agreed: boolean;
}) {
  return (
    <section className={`operator-card operator-${side}`}>
      <div className="operator-identity">
        <div className="operator-avatar">{side.toUpperCase()}</div>
        <div>
          <span className="eyebrow">Operator agent {side.toUpperCase()}</span>
          <h3>{name}</h3>
          <small>NORAD {noradId}</small>
        </div>
      </div>
      <div className="operator-status">
        <i className={active ? 'status-working' : ''} />
        {agreed ? 'Plan signed' : active ? 'Evaluating maneuver' : 'Awaiting mediator'}
      </div>
      <div className="operator-orbit-glyph" aria-hidden="true">
        <svg viewBox="0 0 180 72">
          <ellipse cx="90" cy="36" rx="76" ry="22" transform="rotate(-13 90 36)" />
          <circle cx="90" cy="36" r="13" />
          <circle cx={side === 'a' ? 155 : 25} cy={side === 'a' ? 22 : 51} r="3" />
        </svg>
      </div>
      <p className="feature-footnote">
        Evaluates burn cost, orbital constraints and mission impact for its operator.
      </p>
      <dl className="operator-facts">
        <div>
          <dt>Control authority</dt>
          <dd>Human operator</dd>
        </div>
        <div>
          <dt>Capability</dt>
          <dd>Maneuverable</dd>
        </div>
        <div>
          <dt>Decision scope</dt>
          <dd>Recommendation</dd>
        </div>
      </dl>
    </section>
  );
}

export default function NegotiatorScreen({ conjunctionId, onAgreement }: Props) {
  const query = useConjunction(conjunctionId);
  const [messages, setMessages] = useState<Message[]>([]);
  const [scores, setScores] = useState<Scores | null>(null);
  const [agreement, setAgreement] = useState<Agreement | null>(null);
  const [status, setStatus] = useState<'connecting' | 'streaming' | 'complete' | 'error'>(
    'connecting',
  );
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [sent, setSent] = useState(false);
  const [override, setOverride] = useState('');
  const [overrideOpen, setOverrideOpen] = useState(false);
  const [overrideChoice, setOverrideChoice] = useState('hold');
  const [approvalOpen, setApprovalOpen] = useState(false);
  const [sending, setSending] = useState(false);
  const transcript = useRef<HTMLDivElement>(null);
  const agreementCallback = useRef(onAgreement);
  agreementCallback.current = onAgreement;
  const data = query.data;

  useEffect(() => {
    if (!data || !data.primary.maneuverable || !data.secondary.maneuverable) return;
    const controller = new AbortController();
    setMessages([]);
    setScores(null);
    setAgreement(null);
    setStatus('connecting');
    setError('');
    setSent(false);
    setOverride('');
    const timer = window.setTimeout(() => {
      void (async () => {
        try {
          const { negotiationId } = await api.startNegotiation(data.id, controller.signal);
          if (controller.signal.aborted) return;
          setStatus('streaming');
          await api.streamNegotiation(
            negotiationId,
            (event) => {
              if (controller.signal.aborted) return;
              if (event.type === 'message') setMessages((items) => [...items, event]);
              if (event.type === 'scores') setScores(event);
              if (event.type === 'agreement') {
                setAgreement(event);
                setStatus('complete');
                agreementCallback.current?.(event);
              }
              if (event.type === 'error') {
                setError(event.message);
                setStatus('error');
              }
            },
            controller.signal,
          );
          setStatus((current) => (current === 'streaming' ? 'error' : current));
          setError(
            (current) =>
              current ||
              'The stream ended before an agreement was reached. Reconnect to begin a fresh negotiation.',
          );
        } catch (cause) {
          if (!controller.signal.aborted) {
            setError(
              cause instanceof Error
                ? cause.message
                : 'Connection to the negotiation service was lost.',
            );
            setStatus('error');
          }
        }
      })();
    }, 60);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [data, attempt]);
  useEffect(() => {
    if (transcript.current) transcript.current.scrollTop = transcript.current.scrollHeight;
  }, [messages, scores, agreement]);

  if (query.isPending)
    return (
      <aside className="route-panel route-panel-left feature-state" aria-busy="true">
        <span className="eyebrow">Operator negotiation</span>
        <h2>Loading encounter parameters</h2>
        <p>Loading both operator profiles and the screening result.</p>
        <div className="feature-skeleton" />
      </aside>
    );
  if (query.isError || !data)
    return (
      <aside className="route-panel route-panel-left feature-state">
        <h2>Encounter unavailable</h2>
        <p>{query.error?.message ?? 'The encounter could not be found.'}</p>
        <button className="feature-button" onClick={() => void query.refetch()}>
          Retry connection
        </button>
      </aside>
    );
  if (!data.primary.maneuverable || !data.secondary.maneuverable)
    return (
      <aside className="route-panel route-panel-left feature-state">
        <span className="eyebrow">Negotiation not available</span>
        <h2>One object cannot move.</h2>
        <p>
          This encounter requires action from the maneuverable operator. Open conjunction analysis
          to compare avoidance burns.
        </p>
      </aside>
    );
  const lastSpeaker = messages[messages.length - 1]?.speaker;
  // Numbers the physics produced; agent text that quotes them gets a "physics ✓" tag.
  const known = knownValues(data, agreement ? [agreement] : []);
  const scoreWeight = scores?.criteria.reduce((sum, c) => sum + c.weight, 0) || 1;
  const scoreA = scores
    ? scores.criteria.reduce((sum, c) => sum + c.a * c.weight, 0) / scoreWeight
    : 0;
  const scoreB = scores
    ? scores.criteria.reduce((sum, c) => sum + c.b * c.weight, 0) / scoreWeight
    : 0;
  const sendPlan = async () => {
    setSending(true);
    try {
      if (isMockMode) {
        await new Promise((resolve) => window.setTimeout(resolve, 500));
        setSent(true);
        setApprovalOpen(false);
      } else {
        setError(
          'This API contract does not include operator dispatch. Export or copy the agreed plan to your operations workflow; no plan has been sent.',
        );
      }
    } finally {
      setSending(false);
    }
  };
  return (
    <>
      <aside className="route-panel route-panel-left feature-panel negotiator-operator-panel">
        <header className="feature-panel-heading">
          <span className="eyebrow">Coordinated avoidance</span>
          <span className={`feature-risk ${data.risk}`}>{data.risk}</span>
        </header>
        <h2 className="feature-title">Operator negotiation</h2>
        <p className="feature-description">
          Autonomous agents weigh the trade-offs. Operators retain the final say.
        </p>
        <OperatorCard
          name={data.primary.name}
          noradId={data.primary.noradId}
          side="a"
          active={status === 'streaming' && lastSpeaker !== 'agentA'}
          agreed={!!agreement}
        />
        <div className="negotiator-encounter">
          <span>
            Predicted miss <b>{formatDistance(data.missDistanceM)}</b>
          </span>
          <span>
            Collision probability <b>{formatProbability(data.pc)}</b>
          </span>
          <small>Closest approach {formatUtc(data.tca)}</small>
        </div>
      </aside>
      <aside className="route-panel route-panel-right feature-panel negotiator-decision-panel">
        <OperatorCard
          name={data.secondary.name}
          noradId={data.secondary.noradId}
          side="b"
          active={status === 'streaming' && lastSpeaker !== 'agentB'}
          agreed={!!agreement}
        />
        <section className="feature-section scoring-panel">
          <div className="feature-subheading">
            <h3>Suitability to move</h3>
            <span>Weighted criteria</span>
          </div>
          {scores ? (
            <>
              <div className="score-summary">
                <span>
                  A <b>{scoreA.toFixed(1)}</b>
                </span>
                <span>
                  B <b>{scoreB.toFixed(1)}</b>
                </span>
              </div>
              {scores.criteria.map((criterion) => {
                const max = Math.max(100, criterion.a, criterion.b);
                return (
                  <div className="score-criterion" key={criterion.name}>
                    <div>
                      <span>{criterion.name}</span>
                      <small>
                        {Math.round(
                          criterion.weight <= 1 ? criterion.weight * 100 : criterion.weight,
                        )}
                        % weight
                      </small>
                    </div>
                    <div className="score-bar-row">
                      <span>A</span>
                      <div>
                        <ScoreFill fraction={criterion.a / max} />
                      </div>
                      <b>{criterion.a.toFixed(1)}</b>
                    </div>
                    <div className="score-bar-row b">
                      <span>B</span>
                      <div>
                        <ScoreFill fraction={criterion.b / max} />
                      </div>
                      <b>{criterion.b.toFixed(1)}</b>
                    </div>
                  </div>
                );
              })}
              <WeightExplorer
                criteria={scores.criteria}
                chosen={
                  agreement ? (agreement.mover.noradId === data.primary.noradId ? 'a' : 'b') : null
                }
                nameA={data.primary.name}
                nameB={data.secondary.name}
              />
            </>
          ) : (
            <div className="scoring-empty">
              <div className="feature-skeleton" />
              <p>
                The mediator will score both options after the agents present their constraints.
              </p>
            </div>
          )}
        </section>
        {agreement && (
          <section className="agreement-plan">
            <SignedStamp>
              <span aria-hidden="true">✓</span> Agreement signed
            </SignedStamp>
            <h3>{agreement.mover.name} maneuvers.</h3>
            <dl>
              <div>
                <dt>Proposed burn</dt>
                <dd>
                  {agreement.maneuver.dvMs.toFixed(2)} m/s · {agreement.maneuver.direction}
                </dd>
              </div>
              <div>
                <dt>New miss distance</dt>
                <dd>{formatDistance(agreement.maneuver.newMissM)}</dd>
              </div>
              <div>
                <dt>Propellant cost</dt>
                <dd>{formatPropellant(agreement.maneuver.propellantKg)}</dd>
              </div>
            </dl>
            <small>Signed by {agreement.signedBy.join(' + ')}</small>
            <p>Recommendation only. Humans decide whether to execute.</p>
            <button
              className="feature-button primary full-width"
              onClick={() => setApprovalOpen(true)}
              disabled={sent || !!override}
            >
              {sent ? 'Demo plan delivered' : 'Send plan to both operators'}
            </button>
            <button className="feature-button full-width" onClick={() => setOverrideOpen(true)}>
              Human override
            </button>
            {sent && (
              <p className="feature-success" role="status">
                Sample dispatch completed. No live operators were contacted.
              </p>
            )}
            {override && (
              <p className="feature-success" role="status">
                {override}
              </p>
            )}
          </section>
        )}
      </aside>
      <section
        className="negotiation-transcript feature-float"
        aria-label="Live negotiation transcript"
      >
        <header>
          <div>
            <span className="eyebrow">Live negotiation</span>
            <h3>Negotiation transcript</h3>
            <div
              className="trust-badge"
              title="Agents write the words; every number comes from the physics engine; the decision uses published weights."
            >
              <span>Words: AI</span>
              <span>Numbers: physics</span>
              <span>Decision: published weights</span>
            </div>
          </div>
          <span className={`stream-status ${status}`}>
            <i />
            {status === 'connecting'
              ? 'Connecting'
              : status === 'streaming'
                ? 'Agents online'
                : status === 'complete'
                  ? 'Agreement reached'
                  : 'Connection interrupted'}
          </span>
        </header>
        <div
          className="transcript-scroll"
          ref={transcript}
          role="log"
          aria-live="polite"
          aria-relevant="additions"
        >
          {!messages.length && (
            <div className="transcript-wait">
              <span className="typing-dots">
                <i />
                <i />
                <i />
              </span>
              <p>Opening a secure negotiation session…</p>
            </div>
          )}
          {messages.map((message, index) => (
            <article
              key={`${index}-${message.speaker}`}
              className={`transcript-message ${message.speaker}`}
            >
              <div>
                <span>
                  {message.speaker === 'mediator'
                    ? 'SENTINEL · MEDIATOR'
                    : message.speaker === 'agentA'
                      ? `${data.primary.name} · AGENT A`
                      : `${data.secondary.name} · AGENT B`}
                </span>
                <small>ROUND {message.round}</small>
              </div>
              <PhysicsText text={message.text} known={known} />
            </article>
          ))}
          {status === 'streaming' && (
            <div className="transcript-typing">
              <span className="typing-dots">
                <i />
                <i />
                <i />
              </span>
              <span>
                {lastSpeaker === 'agentA'
                  ? 'Agent B'
                  : lastSpeaker === 'agentB'
                    ? 'Mediator'
                    : 'Agents'}{' '}
                evaluating…
              </span>
            </div>
          )}
          {status === 'error' && (
            <div className="feature-stream-error" role="alert">
              <p>{error || 'The negotiation stream stopped before an agreement.'}</p>
              <button className="feature-button" onClick={() => setAttempt((value) => value + 1)}>
                Restart negotiation
              </button>
            </div>
          )}
        </div>
        <footer>
          {isMockMode
            ? 'Sample agent exchange · simulated negotiation stream'
            : 'AI-generated recommendations · operator approval required'}
        </footer>
      </section>
      <Dialog.Root open={overrideOpen} onOpenChange={setOverrideOpen}>
        <Dialog.Portal>
          <Dialog.Overlay className="feature-modal-overlay" />
          <Dialog.Content className="feature-modal">
            <Dialog.Title>Operator override</Dialog.Title>
            <Dialog.Description>
              Record your decision for this planning session. No burn commands will be issued.
            </Dialog.Description>
            <label className="feature-field">
              Decision
              <select
                value={overrideChoice}
                onChange={(event) => setOverrideChoice(event.target.value)}
              >
                <option value="hold">Hold for manual analysis</option>
                <option value="reject">Reject the proposed maneuver</option>
                <option value="alternate">Request an alternate burn</option>
              </select>
            </label>
            <div className="feature-modal-actions">
              <Dialog.Close className="feature-button">Cancel</Dialog.Close>
              <button
                className="feature-button primary"
                onClick={() => {
                  setOverride(
                    overrideChoice === 'hold'
                      ? 'Plan held for manual operator review.'
                      : overrideChoice === 'reject'
                        ? 'Proposed maneuver rejected by the operator.'
                        : 'Alternate burn requested. Plan held for review.',
                  );
                  setOverrideOpen(false);
                }}
              >
                Record override
              </button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
      <Dialog.Root open={approvalOpen} onOpenChange={setApprovalOpen}>
        <Dialog.Portal>
          <Dialog.Overlay className="feature-modal-overlay" />
          <Dialog.Content className="feature-modal">
            <Dialog.Title>Review operator handoff</Dialog.Title>
            <Dialog.Description>
              {isMockMode
                ? 'This is a sample dispatch. The signed recommendation is staged for both operators; no real messages or burn commands will be sent.'
                : 'The current backend API supports planning only. Operator dispatch is not configured; this action will explain the handoff requirement.'}
            </Dialog.Description>
            <p className="approval-summary">
              {agreement?.mover.name} · {agreement?.maneuver.dvMs.toFixed(2)} m/s{' '}
              {agreement?.maneuver.direction}
              <br />
              Resulting miss: {agreement ? formatDistance(agreement.maneuver.newMissM) : '—'}
            </p>
            {error && !isMockMode && <p role="status">{error}</p>}
            <div className="feature-modal-actions">
              <Dialog.Close className="feature-button">Keep reviewing</Dialog.Close>
              <button
                className="feature-button primary"
                disabled={sending}
                onClick={() => void sendPlan()}
              >
                {sending
                  ? 'Staging…'
                  : isMockMode
                    ? 'Confirm sample dispatch'
                    : 'Check dispatch availability'}
              </button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </>
  );
}

import { useEffect, useState } from 'react';
import { useConjunction } from '../../api/hooks';
import { isMockMode } from '../../api/client';
import { useSimStore } from '../../sim/clock';
import {
  formatCountdown,
  formatDistance,
  formatProbability,
  formatUtc,
  formatUtcDate,
  probabilityOdds,
} from '../../lib/format';

interface Props {
  id: string;
  onReview: () => void;
}

export default function AlertScreen({ id, onReview }: Props) {
  const query = useConjunction(id);
  const timeMs = useSimStore((state) => state.timeMs);
  const [acknowledgedAt, setAcknowledgedAt] = useState<number | null>(null);
  useEffect(() => setAcknowledgedAt(null), [id]);

  if (query.isPending) {
    return (
      <section className="route-panel route-panel-right orbit-alert feature-panel" aria-busy="true">
        <span className="eyebrow">Conjunction alert</span>
        <h2 className="feature-title">Resolving the encounter.</h2>
        <p className="feature-description">
          Loading the screening result and recommended response.
        </p>
        <div className="feature-skeleton" />
        <div className="feature-skeleton short" />
      </section>
    );
  }

  if (query.isError || !query.data) {
    return (
      <section className="route-panel route-panel-right orbit-alert feature-panel" role="alert">
        <span className="eyebrow">Conjunction alert</span>
        <h2 className="feature-title">Alert details unavailable.</h2>
        <p className="feature-description">
          {query.error?.message ?? 'This encounter is not in the latest screening run.'}
        </p>
        <button className="feature-button full-width" onClick={() => void query.refetch()}>
          Retry alert
        </button>
      </section>
    );
  }

  const data = query.data;
  const maneuver = data.options.find((option) => option.recommended);
  const isPast = Date.parse(data.tca) < timeMs;

  return (
    <section
      className={`route-panel route-panel-right orbit-alert feature-panel alert-${data.risk}`}
      aria-labelledby="orbit-alert-title"
    >
      <header className="feature-panel-heading">
        <span className={`feature-risk ${data.risk}`}>{data.risk} conjunction</span>
        {isMockMode && <span className="feature-status">Sample data</span>}
      </header>
      <h2 id="orbit-alert-title" className="alert-headline">
        Conjunction alert
      </h2>
      <div className="alert-object-pair">
        <span>
          <i className="object-dot satellite" />
          {data.primary.name}
        </span>
        <small>×</small>
        <span>
          <i className="object-dot debris" />
          {data.secondary.name}
        </span>
      </div>
      <div className="alert-countdown">
        <span className="eyebrow">
          {isPast ? 'Time since closest approach' : 'Time to closest approach'}
        </span>
        <strong>{formatCountdown(data.tca, timeMs)}</strong>
        <small>{formatUtcDate(data.tca)}</small>
      </div>
      <dl className="alert-three-metrics">
        <div>
          <dt>Miss distance</dt>
          <dd>{formatDistance(data.missDistanceM)}</dd>
        </div>
        <div>
          <dt>Collision probability</dt>
          <dd>{formatProbability(data.pc)}</dd>
          <small>{probabilityOdds(data.pc)}</small>
        </div>
        <div>
          <dt>Relative speed</dt>
          <dd>
            {data.relSpeedKms.toFixed(1)} <small>km/s</small>
          </dd>
        </div>
      </dl>
      <section className="alert-recommended-burn" aria-label="Recommended response">
        <span className="eyebrow">Recommended response</span>
        {maneuver ? (
          <>
            <h3>
              {maneuver.direction === 'none'
                ? 'Maintain the current trajectory.'
                : `${maneuver.dvMs.toFixed(2)} m/s ${maneuver.direction} burn`}
            </h3>
            <p>
              {maneuver.burnAt ? `Proposed burn at ${formatUtc(maneuver.burnAt)}. ` : ''}Predicted
              separation becomes <b>{formatDistance(maneuver.newMissM)}</b>.
            </p>
            <small>Human operator approval required before execution.</small>
          </>
        ) : (
          <>
            <h3>Review the encounter.</h3>
            <p>
              No recommended burn was returned. Inspect the uncertainty and available options before
              deciding.
            </p>
          </>
        )}
      </section>
      {!data.secondary.maneuverable && (
        <p className="alert-response-note">
          {data.secondary.name} cannot maneuver. The primary operator must review the response.
        </p>
      )}
      <div className="alert-actions">
        <button className="feature-button primary full-width" onClick={onReview}>
          Review options <span aria-hidden="true">↗</span>
        </button>
        <button
          className="feature-button full-width"
          disabled={acknowledgedAt !== null}
          onClick={() => setAcknowledgedAt(Date.now())}
          aria-describedby="alert-acknowledgement-status"
        >
          {acknowledgedAt === null ? 'Acknowledge alert' : 'Alert acknowledged'}
        </button>
      </div>
      <p
        id="alert-acknowledgement-status"
        className={`alert-acknowledgement ${acknowledgedAt ? 'acknowledged' : ''}`}
        role="status"
      >
        {acknowledgedAt
          ? `Acknowledged at ${formatUtc(acknowledgedAt)} for this session. Review the burn separately.`
          : 'Acknowledgement records your review in this session.'}
      </p>
    </section>
  );
}

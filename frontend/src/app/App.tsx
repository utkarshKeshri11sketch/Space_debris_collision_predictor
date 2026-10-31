import { lazy, Suspense, useCallback, useDeferredValue, useEffect, useMemo, useState } from 'react';
import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom';
import * as Dialog from '@radix-ui/react-dialog';
import { useCatalog, useCatalogMeta, useConjunction, useConjunctions } from '../api/hooks';
import { api, isMockMode } from '../api/client';
import type { CascadeResult, CatalogObject, Conjunction } from '../api/types';
import { SimClockTicker, useSimStore } from '../sim/clock';
import { Icon } from '../ui/Icon';
import Ticker from '../ui/Ticker';
import { ThreatRow } from '../ui/DemoMotion';
import ObjectInspector from '../features/mission-control/ObjectInspector';
import '../features/features.css';
import '../styles/console.css';
import '../styles/usp.css';

const OrbitalScene = lazy(() => import('../scene/OrbitalScene'));
const ConjunctionScreen = lazy(() => import('../features/conjunction/ConjunctionScreen'));
const NegotiatorScreen = lazy(() => import('../features/negotiator/NegotiatorScreen'));
const CascadeScreen = lazy(() => import('../features/cascade/CascadeScreen'));
const AlertScreen = lazy(() => import('../features/conjunction/AlertScreen'));
const CaseStudyScreen = lazy(() => import('../features/case-study/CaseStudyScreen'));
const CollisionStudyScreen = lazy(() => import('../features/case-study/CollisionStudyScreen'));
const speeds = [1, 60, 600, 3600];
// Backend Ask Sentinel refusals (app/ai/ask.py OFF_TOPIC / NOT_IN_RUN).
const REFUSAL = /^(I can only help with|That isn't in the current screening run)/;
const utc = (ms: number) => new Date(ms).toISOString().slice(11, 19);
const dateUtc = (ms: number) => new Date(ms).toISOString().slice(0, 10);
const compact = (n: number) => n.toLocaleString('en-US');
const relative = (date: string, time: number) => {
  const d = Math.max(0, new Date(date).getTime() - time);
  return `${Math.floor(d / 3600000)
    .toString()
    .padStart(2, '0')}h ${Math.floor((d / 60000) % 60)
    .toString()
    .padStart(2, '0')}m`;
};

export default function App() {
  const location = useLocation();
  const navigate = useNavigate();
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [focusNonce, setFocusNonce] = useState(0);
  const [layers, setLayers] = useState({ payload: true, debris: true, rocket: true });
  const [regime, setRegime] = useState<'ALL' | 'LEO' | 'MEO' | 'GEO'>('ALL');
  const [density, setDensity] = useState(false);
  const [quality, setQuality] = useState<'high' | 'low'>(() =>
    navigator.hardwareConcurrency < 6 ? 'low' : 'high',
  );
  const [palette, setPalette] = useState(false);
  const [settings, setSettings] = useState(false);
  const [shortcuts, setShortcuts] = useState(false);
  const [toast, setToast] = useState('');
  const [cascade, setCascade] = useState<CascadeResult>();
  const [cascadeYear, setCascadeYear] = useState(0);
  const [previewBurn, setPreviewBurn] = useState(false);
  const [replayProgress, setReplayProgress] = useState<number>();
  const [mobilePanel, setMobilePanel] = useState<'layers' | 'threats'>('threats');
  const [intro, setIntro] = useState(
    () =>
      !sessionStorage.getItem('orbit-intro') &&
      !matchMedia('(prefers-reduced-motion: reduce)').matches,
  );
  // The Cascade Lab's case study opens over the scene like Rewind 2021, under the Cascade Lab tab.
  const rewind2009 = location.pathname.startsWith('/cascade/rewind-2009');
  const mode =
    location.pathname.startsWith('/case-study') || rewind2009
      ? 'casestudy'
      : location.pathname.startsWith('/cascade')
        ? 'cascade'
        : location.pathname.startsWith('/negotiator')
          ? 'negotiator'
          : location.pathname.startsWith('/conjunctions') || location.pathname.startsWith('/alert')
            ? 'conjunction'
            : 'mission';
  const eventId =
    location.pathname.split('/')[2] || (mode === 'negotiator' ? 'starlink-oneweb' : 'iss-cosmos');
  const threats = useConjunctions();
  const detail = useConjunction(mode === 'conjunction' || mode === 'negotiator' ? eventId : '');
  const conjunction = detail.data ?? threats.data?.find((c) => c.id === eventId);
  const { data: catalog } = useCatalog();
  const selected = catalog?.find((o) => o.noradId === selectedId);
  const finishIntro = useCallback(() => {
    sessionStorage.setItem('orbit-intro', '1');
    setIntro(false);
  }, []);
  useEffect(() => {
    if (!intro) return;
    const timeout = setTimeout(finishIntro, 6200);
    return () => clearTimeout(timeout);
  }, [intro, finishIntro]);
  useEffect(() => {
    setPreviewBurn(false);
    setReplayProgress(undefined);
    setSelectedId(null);
  }, [location.pathname]);
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(''), 6500);
    return () => clearTimeout(timer);
  }, [toast]);
  useEffect(() => {
    const critical = threats.data?.find((c) => c.risk === 'critical');
    if (intro || !critical) return;
    const timer = setTimeout(
      () =>
        setToast(
          `Critical conjunction detected · ${critical.primary.name} / ${critical.secondary.name} · ${compact(critical.missDistanceM)} m`,
        ),
      3500,
    );
    return () => clearTimeout(timer);
  }, [intro, threats.data]);
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const target = e.target as HTMLElement;
      if (target.matches('input,textarea,select') || target.isContentEditable) return;
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setPalette((v) => !v);
        return;
      }
      if (e.key === 'Escape') {
        setSelectedId(null);
        if (mode !== 'mission') navigate('/');
        return;
      }
      if (e.code === 'Space') {
        e.preventDefault();
        useSimStore.getState().togglePlaying();
      }
      if (e.key === '[' || e.key === ']') {
        const clock = useSimStore.getState();
        const index = speeds.indexOf(clock.speed);
        clock.setSpeed(speeds[Math.max(0, Math.min(3, index + (e.key === ']' ? 1 : -1)))]);
      }
      if (e.key.toLowerCase() === 'f') setFocusNonce((v) => v + 1);
      if (e.key === '?') setShortcuts(true);
      if (e.shiftKey && e.key.toLowerCase() === 'd' && import.meta.env.DEV)
        document.body.classList.toggle('show-debug');
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [mode, navigate]);
  const selectObject = (id: number | null) => {
    setSelectedId(id);
    setPalette(false);
  };
  const focusObject = (id: number) => {
    setSelectedId(id);
    setFocusNonce((v) => v + 1);
    setPalette(false);
  };
  const negotiate = (id: string) => navigate(`/negotiator/${id}`);
  const navNegotiation = threats.data?.find(
    (c) => c.primary.maneuverable && c.secondary.maneuverable,
  )?.id;
  return (
    <div
      className={`application mode-${mode} mobile-${mobilePanel}${selectedId !== null ? ' has-selection' : ''}`}
    >
      <SimClockTicker />
      <a className="skip-link" href="#workspace">
        Skip to mission data
      </a>
      <header className="topbar">
        <Link to="/" className="wordmark" aria-label="OrbitSentinel mission control">
          <svg viewBox="0 0 40 40" width="35" height="35" fill="none" aria-hidden="true">
            <circle cx="20" cy="20" r="8" stroke="currentColor" strokeWidth="1.4" />
            <ellipse
              cx="20"
              cy="20"
              rx="19"
              ry="7"
              transform="rotate(-39 20 20)"
              stroke="currentColor"
              strokeWidth="1.4"
            />
            <circle cx="29" cy="12" r="3" fill="var(--accent)" />
          </svg>
          <span>
            ORBIT<span className="wordmark-light">SENTINEL</span>
            <small>ORBITAL INTELLIGENCE</small>
          </span>
        </Link>
        <nav className="main-nav" aria-label="Main navigation">
          <NavLink to="/" end>
            Mission Control
          </NavLink>
          <NavLink to={`/conjunctions/${threats.data?.[0]?.id ?? 'iss-cosmos'}`}>
            Conjunctions
          </NavLink>
          <NavLink to={`/negotiator/${navNegotiation ?? 'starlink-oneweb'}`}>Negotiator</NavLink>
          <NavLink to="/cascade">Cascade Lab</NavLink>
          <NavLink to="/case-study">Rewind 2021</NavLink>
        </nav>
        <div className="topbar-tools">
          <span className="sync">
            <i />
            Systems nominal
          </span>
          <button className="ask-button" aria-label="Ask Sentinel" onClick={() => setPalette(true)}>
            <Icon name="search" size={16} />
            <span>Ask Sentinel</span>
            <kbd>⌘ K</kbd>
          </button>
          <button
            className="icon-button settings-button"
            aria-label="Settings"
            onClick={() => setSettings(true)}
          >
            <Icon name="settings" />
          </button>
        </div>
      </header>
      <main id="workspace" className="workspace">
        <div
          className="scene-layer"
          aria-label="Interactive orbital environment. Use object search or the threats list for a text alternative."
        >
          <Suspense
            fallback={
              <div className="scene-loading">
                <div className="loading-orbit" />
                INITIALIZING ORBITAL ENVIRONMENT
              </div>
            }
          >
            <OrbitalScene
              mode={mode === 'casestudy' ? 'mission' : mode}
              selectedId={selectedId}
              conjunction={
                mode === 'conjunction' || mode === 'negotiator' ? conjunction : undefined
              }
              cascade={cascade}
              cascadeYear={cascadeYear}
              layers={layers}
              regime={regime}
              density={density}
              quality={quality}
              focusNonce={focusNonce}
              onSelect={selectObject}
              replayProgress={replayProgress}
              previewBurn={previewBurn}
              introActive={intro}
            />
          </Suspense>
        </div>
        <div className="viewport-corners" aria-hidden="true">
          <i />
          <i />
          <i />
          <i />
        </div>
        <div className="workspace-heading">
          <div>
            <div className="eyebrow">
              Mission control <span className="eyebrow-separator">/</span>{' '}
              {mode === 'mission'
                ? selected
                  ? `Focus mode · ${selected.name}`
                  : 'Orbital environment'
                : mode === 'casestudy'
                  ? 'REAL INCIDENT · REPLAYED'
                  : mode === 'cascade'
                    ? 'LONG-TERM EVOLUTION'
                    : mode === 'negotiator'
                      ? 'OPERATOR COORDINATION'
                      : 'ENCOUNTER ANALYSIS'}
            </div>
            <h1>
              {mode === 'mission'
                ? 'Orbital overview'
                : mode === 'casestudy'
                  ? rewind2009
                    ? 'Rewind 2009'
                    : 'Rewind 2021'
                  : mode === 'cascade'
                    ? 'Cascade simulation'
                    : mode === 'negotiator'
                      ? 'Operator coordination'
                      : 'Conjunction analysis'}
            </h1>
          </div>
          <div className="heading-right">
            {isMockMode && <span className="sample-tag">Sample data</span>}
            <span className="screening-tag">
              <i />
              SCREENING WINDOW <b>7 DAYS</b>
            </span>
          </div>
        </div>
        {mode === 'mission' ? (
          <>
            <MissionLayers
              layers={layers}
              onLayers={setLayers}
              regime={regime}
              onRegime={setRegime}
              density={density}
              onDensity={setDensity}
              onSearch={() => setPalette(true)}
            />
            {selected ? (
              <ObjectInspector
                key={selected.noradId}
                object={selected}
                nextApproach={threats.data?.find(
                  (event) =>
                    event.primary.noradId === selected.noradId ||
                    event.secondary.noradId === selected.noradId,
                )}
                onClose={() => setSelectedId(null)}
                onFocus={() => setFocusNonce((v) => v + 1)}
                onViewConjunctions={(id) => navigate(`/conjunctions/${id}`)}
              />
            ) : (
              <MissionThreats
                threats={threats.data}
                isPending={threats.isPending}
                isError={threats.isError}
                onRetry={() => void threats.refetch()}
                onOpen={(id) =>
                  navigate(`${window.innerWidth < 768 ? '/alert' : '/conjunctions'}/${id}`)
                }
              />
            )}
            <div className="scene-caption">
              <span className="small-cross">+</span>
              <div>
                <span>EARTH ORBITAL ENVIRONMENT</span>
                <small>
                  TEME REFERENCE FRAME <b>•</b> SGP4 PROPAGATION
                </small>
              </div>
            </div>
            <MissionMetrics threats={threats.data} />
            <div className="scene-utilities">
              <button
                className="icon-button"
                title="Reset global view"
                aria-label="Reset global view"
                onClick={() => {
                  setSelectedId(null);
                  setFocusNonce((v) => v + 1);
                }}
              >
                <Icon name="globe" />
              </button>
              <button
                className="icon-button"
                title="Focus selected object (F)"
                aria-label="Focus selected object"
                onClick={() => setFocusNonce((v) => v + 1)}
              >
                <Icon name="target" />
              </button>
              <button
                className="icon-button"
                title="Search catalog"
                aria-label="Search catalog"
                onClick={() => setPalette(true)}
              >
                <Icon name="search" />
              </button>
              <div className="scale-bar">
                <span />
                6,371 km
              </div>
            </div>
            <div className="mobile-panel-tabs">
              <button
                className={mobilePanel === 'layers' ? 'active' : ''}
                onClick={() => setMobilePanel('layers')}
              >
                Layers & brief
              </button>
              <button
                className={mobilePanel === 'threats' ? 'active' : ''}
                onClick={() => setMobilePanel('threats')}
              >
                Conjunctions ({threats.data?.length ?? 0})
              </button>
            </div>
          </>
        ) : (
          <Suspense
            fallback={
              <div className="route-panel route-panel-right panel-loading">
                Loading mission data…
              </div>
            }
          >
            {mode === 'conjunction' &&
              (location.pathname.startsWith('/alert') ? (
                <AlertScreen
                  key={eventId}
                  id={eventId}
                  onReview={() => navigate(`/conjunctions/${eventId}`)}
                />
              ) : (
                <ConjunctionScreen
                  key={eventId}
                  id={eventId}
                  onReplay={setReplayProgress}
                  onPreviewBurn={setPreviewBurn}
                  onNegotiate={negotiate}
                />
              ))}
            {mode === 'negotiator' && (
              <NegotiatorScreen
                key={eventId}
                conjunctionId={eventId}
                onAgreement={() => setPreviewBurn(true)}
              />
            )}
            {mode === 'cascade' && <CascadeScreen onResult={setCascade} onYear={setCascadeYear} />}
            {mode === 'casestudy' && rewind2009 && (
              <CollisionStudyScreen onCascade={() => navigate('/cascade')} />
            )}
            {mode === 'casestudy' && !rewind2009 && (
              <CaseStudyScreen
                caseId={location.pathname.split('/')[2] || undefined}
                onSelect={(id) => navigate(`/case-study/${id}`)}
              />
            )}
          </Suspense>
        )}
        {mode !== 'mission' && (
          <Link className="back-overview" to="/">
            <Icon name="arrow" size={15} style={{ transform: 'rotate(180deg)' }} />
            Global overview
          </Link>
        )}
        <TimeBar threats={threats.data ?? []} />
      </main>
      <footer className="statusbar">
        <span>
          <i className="status-dot" />{' '}
          {isMockMode ? 'DEMO ENVIRONMENT · RUNS OFFLINE' : 'BACKEND CONNECTED'} <b>/</b>{' '}
          ORBITSENTINEL v1.0
        </span>
        <span>
          SGP4 · WGS-72 <b>/</b>{' '}
          <button onClick={() => setShortcuts(true)}>
            Keyboard shortcuts <kbd>?</kbd>
          </button>
        </span>
      </footer>
      {toast && (
        <div
          className={`toast ${toast.startsWith('Critical') ? 'toast-critical' : ''}`}
          role="status"
        >
          <Icon name="alert" />
          <span>{toast}</span>
          <button
            className="icon-button"
            aria-label="Dismiss notification"
            onClick={() => setToast('')}
          >
            <Icon name="close" size={16} />
          </button>
        </div>
      )}
      <CommandPalette
        open={palette}
        onOpenChange={setPalette}
        catalog={catalog ?? []}
        threats={threats.data ?? []}
        onSelect={focusObject}
        onEvent={(id) => {
          setPalette(false);
          navigate(`/conjunctions/${id}`);
        }}
      />
      <Modal
        open={settings}
        onOpenChange={setSettings}
        title="Display settings"
        description="Adjust rendering for the machine running your demo."
      >
        <label className="field-label">RENDERING QUALITY</label>
        <div className="segmented">
          <button onClick={() => setQuality('high')} className={quality === 'high' ? 'active' : ''}>
            High fidelity
          </button>
          <button onClick={() => setQuality('low')} className={quality === 'low' ? 'active' : ''}>
            Performance
          </button>
        </div>
        <p className="muted">
          Performance mode uses fewer stars and simpler atmospheric detail. The complete object
          catalog remains available.
        </p>
        <div className="settings-note">
          <Icon name="shield" />
          <span>
            {isMockMode
              ? 'All conjunctions and recommendations use sample data.'
              : 'Data is provided by the configured backend.'}{' '}
            OrbitSentinel is a decision support demonstration.
          </span>
        </div>
      </Modal>
      <Modal
        open={shortcuts}
        onOpenChange={setShortcuts}
        title="Mission shortcuts"
        description="Move around the console without leaving the keyboard."
      >
        <div className="shortcut-list">
          {[
            ['Ctrl / ⌘ + K', 'Search objects or ask Sentinel'],
            ['Space', 'Play or pause simulation'],
            ['[ / ]', 'Decrease or increase time speed'],
            ['F', 'Focus selected object'],
            ['Esc', 'Return to global overview'],
            ['?', 'Open this reference'],
          ].map(([key, text]) => (
            <div key={key}>
              <span>{text}</span>
              <kbd>{key}</kbd>
            </div>
          ))}
        </div>
      </Modal>
      {intro && <Intro onSkip={finishIntro} objectCount={catalog?.length ?? 0} />}
    </div>
  );
}

function MissionLayers({
  layers,
  onLayers,
  regime,
  onRegime,
  density,
  onDensity,
  onSearch,
}: {
  layers: { payload: boolean; debris: boolean; rocket: boolean };
  onLayers: (v: typeof layers) => void;
  regime: 'ALL' | 'LEO' | 'MEO' | 'GEO';
  onRegime: (v: typeof regime) => void;
  density: boolean;
  onDensity: (v: boolean) => void;
  onSearch: () => void;
}) {
  const meta = useCatalogMeta();
  const { data: catalog } = useCatalog();
  return (
    <aside className="mission-left">
      <section className="panel layers-panel">
        <div className="panel-heading">
          <span>
            <Icon name="layers" size={16} />
            Display layers
          </span>
          <span className="micro">03</span>
        </div>
        <div className="panel-body">
          <div className="label-line">
            OBJECT CLASS<span>TRACKED</span>
          </div>
          {(
            [
              { key: 'payload', label: 'Satellites', type: 'PAYLOAD', color: 'var(--sat)' },
              { key: 'debris', label: 'Debris', type: 'DEBRIS', color: 'var(--debris)' },
              {
                key: 'rocket',
                label: 'Rocket bodies',
                type: 'ROCKET_BODY',
                color: 'var(--rocket)',
              },
            ] as const
          ).map((l) => (
            <label className="layer-row" key={l.key}>
              <input
                type="checkbox"
                checked={layers[l.key]}
                onChange={(e) => onLayers({ ...layers, [l.key]: e.target.checked })}
              />
              <span className="object-dot" style={{ background: l.color }} />
              <span>{l.label}</span>
              <b>{compact(catalog?.filter((o) => o.type === l.type).length ?? 0)}</b>
            </label>
          ))}
          <div className="divider" />
          <div className="label-line">ORBITAL REGIME</div>
          <div className="segmented regime-control">
            {(['ALL', 'LEO', 'MEO', 'GEO'] as const).map((r) => (
              <button key={r} className={regime === r ? 'active' : ''} onClick={() => onRegime(r)}>
                {r === 'ALL' ? 'All' : r}
              </button>
            ))}
          </div>
          <div className="regime-description">
            {regime === 'ALL'
              ? 'Low, medium & geostationary orbit'
              : regime === 'LEO'
                ? 'Low Earth orbit · below 2,000 km'
                : regime === 'MEO'
                  ? 'Medium Earth orbit · 2,000–35,786 km'
                  : 'Geostationary orbit · ~35,786 km'}
          </div>
          <div className="divider" />
          <label className="density-toggle">
            <span>Altitude density</span>
            <input
              role="switch"
              type="checkbox"
              checked={density}
              onChange={(e) => onDensity(e.target.checked)}
            />
            <span className="switch-track" />
          </label>
          <button className="catalog-search" onClick={onSearch}>
            <Icon name="search" size={15} />
            Find an object <kbd>⌘ K</kbd>
          </button>
          <div className="catalog-sync">
            <i />
            {meta.isError
              ? 'Catalog metadata unavailable'
              : meta.isPending
                ? 'Synchronizing catalog…'
                : `Catalog synced · ${utc(new Date(meta.data?.syncedAt ?? Date.now()).getTime())} UTC`}
          </div>
        </div>
      </section>
      <SentinelBrief />
      <div className="left-note">
        <Icon name="shield" size={15} />
        <span>
          One shared orbital environment.
          <br />
          Every object accounted for.
        </span>
      </div>
    </aside>
  );
}

function SentinelBrief() {
  const [visible, setVisible] = useState(0);
  const threats = useConjunctions();
  const detail = useConjunction(threats.data?.[0]?.id);
  const text =
    detail.data?.brief ??
    (detail.isError
      ? 'The screening brief is unavailable. Review the conjunction data directly.'
      : threats.data?.length === 0
        ? 'No close approaches were returned for this screening window. Continue monitoring catalog updates.'
        : 'Loading the latest screening brief…');
  useEffect(() => {
    setVisible(0);
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setVisible(text.length);
      return;
    }
    const t = setInterval(() => setVisible((v) => Math.min(text.length, v + 5)), 24);
    return () => clearInterval(t);
  }, [text]);
  return (
    <section className="panel brief-panel">
      <div className="panel-heading">
        <span>
          <span className="sentinel-mark">S</span>Sentinel brief
        </span>
        <span className="micro">01 / 07</span>
      </div>
      <div className="panel-body">
        <div className="brief-label">YOUR NEXT DECISION</div>
        <p>
          {text.slice(0, visible)}
          {visible < text.length && <span className="typing-cursor" />}
        </p>
        <div className="brief-attribution">
          {isMockMode ? 'Sample AI brief · backend-ready' : 'Brief from the screening API'}
        </div>
      </div>
    </section>
  );
}

function MissionThreats({
  threats,
  isPending,
  isError,
  onRetry,
  onOpen,
}: {
  threats: Conjunction[] | undefined;
  isPending: boolean;
  isError: boolean;
  onRetry: () => void;
  onOpen: (id: string) => void;
}) {
  const time = useSimStore((s) => s.timeMs);
  const [threshold, setThreshold] = useState('all');
  const visible = threats?.filter(
    (t) => threshold === 'all' || (threshold === 'critical' ? t.risk === 'critical' : t.pc >= 1e-5),
  );
  return (
    <aside className="panel mission-threats">
      <div className="panel-heading">
        <span>Conjunction watch</span>
        <span className="count-pill">{visible?.length ?? '—'}</span>
      </div>
      <div className="threats-subhead">
        <span>NEXT 7 DAYS</span>
        <select
          aria-label="Collision probability threshold"
          value={threshold}
          onChange={(e) => setThreshold(e.target.value)}
        >
          <option value="all">All risks · Pc ≥ 10⁻⁶</option>
          <option value="high">Pc ≥ 10⁻⁵</option>
          <option value="critical">Critical only</option>
        </select>
      </div>
      <div className="threat-list">
        {isPending ? (
          <div className="skeleton-list">
            {[1, 2, 3, 4].map((i) => (
              <div className="skeleton" key={i} />
            ))}
          </div>
        ) : isError ? (
          <div className="fetch-state">
            <Icon name="alert" />
            <p>Screening data is unavailable.</p>
            <button className="secondary-button" onClick={onRetry}>
              Retry screening
            </button>
          </div>
        ) : !visible?.length ? (
          <div className="fetch-state">
            <Icon name="shield" />
            <p>No conjunctions match this threshold.</p>
            <small>The catalog remains available on the globe.</small>
          </div>
        ) : (
          visible.map((c, i) => (
            <ThreatRow
              index={i}
              key={c.id}
              className={`threat-row threat-${c.risk}`}
              onClick={() => onOpen(c.id)}
            >
              <div className="threat-topline">
                <span className={`risk-badge ${c.risk}`}>
                  {c.risk === 'critical' && <span />}
                  {c.risk.toUpperCase()}
                </span>
                <span className="threat-countdown">T− {relative(c.tca, time)}</span>
              </div>
              <div className="threat-object">{c.primary.name}</div>
              <div className="threat-secondary">
                <span className="orbit-cross">×</span>
                {c.secondary.name}
              </div>
              <div className="threat-values">
                <div>
                  <strong>{compact(c.missDistanceM)}</strong>
                  <small> m miss</small>
                </div>
                <span>
                  Pc <b>{c.pc.toExponential(1)}</b>
                </span>
                <Icon name="chevron" size={15} />
              </div>
              {i === 0 && (
                <div className="critical-link">
                  Review avoidance options
                  <Icon name="arrow" size={14} />
                </div>
              )}
            </ThreatRow>
          ))
        )}
      </div>
      <div className="threats-footer">
        <i />
        Screened against the full catalog <span>↗</span>
      </div>
    </aside>
  );
}

function MissionMetrics({ threats }: { threats: Conjunction[] | undefined }) {
  const meta = useCatalogMeta();
  return (
    <div className="mission-metrics">
      {[
        {
          label: 'OBJECTS TRACKED',
          value: <Ticker value={meta.data?.objectCount} />,
          unit: 'objects',
        },
        { label: 'CLOSE APPROACHES', value: <Ticker value={threats?.length} />, unit: '/ 7 days' },
        {
          label: 'HIGH + CRITICAL',
          value: (
            <Ticker
              value={threats?.filter((c) => c.risk !== 'watch').length}
              format={(n) => Math.round(n).toString().padStart(2, '0')}
            />
          ),
          unit: 'events',
          warn: true,
        },
      ].map((s) => (
        <div className="mission-stat" key={s.label}>
          <span>{s.label}</span>
          <div className={s.warn ? 'warn-number' : ''}>
            {s.value}
            <small>{s.unit}</small>
          </div>
        </div>
      ))}
    </div>
  );
}

function TimeBar({ threats }: { threats: Conjunction[] }) {
  const { timeMs, epochMs, playing, speed, togglePlaying, setSpeed, setTime } = useSimStore();
  const pct = Math.max(0, Math.min(100, ((timeMs - epochMs) / (7 * 86400000)) * 100));
  return (
    <div className="timebar">
      <div className="timebar-top">
        <div className="timeline-label">
          <i className={playing ? 'status-dot' : ''} />
          {playing ? 'SIMULATION RUNNING' : 'SIMULATION PAUSED'}
        </div>
        <div className="sim-utc">
          <strong>{dateUtc(timeMs)}</strong>
          <b>{utc(timeMs)}</b> UTC{' '}
          <button title="Reset to current time" onClick={() => setTime(Date.now())}>
            NOW
            <Icon name="refresh" size={12} />
          </button>
        </div>
      </div>
      <div className="timebar-bottom">
        <button
          className="play-button"
          onClick={togglePlaying}
          aria-label={playing ? 'Pause simulation' : 'Play simulation'}
        >
          <Icon name={playing ? 'pause' : 'play'} size={16} />
        </button>
        <div className="speed-control" aria-label="Simulation speed">
          {speeds.map((s) => (
            <button key={s} onClick={() => setSpeed(s)} className={speed === s ? 'active' : ''}>
              {s}×
            </button>
          ))}
        </div>
        <div className="timeline-track">
          <div className="timeline-events">
            {threats.map((c) => (
              <button
                title={`${c.primary.name}: ${utc(Date.parse(c.tca))} UTC`}
                key={c.id}
                aria-label={`Jump to ${c.primary.name} encounter`}
                style={{
                  left: `${Math.max(0, Math.min(100, ((Date.parse(c.tca) - epochMs) / (7 * 86400000)) * 100))}%`,
                }}
                onClick={() => setTime(Date.parse(c.tca))}
                className={c.risk}
              />
            ))}
          </div>
          <input
            type="range"
            min="0"
            max="100"
            step="0.01"
            value={pct}
            aria-label="Simulation time, now to seven days"
            onChange={(e) => setTime(epochMs + (Number(e.target.value) / 100) * 7 * 86400000)}
            style={{ '--progress': `${pct}%` } as React.CSSProperties}
          />
          <div className="timeline-ticks">
            <span>NOW</span>
            {[1, 2, 3, 4, 5, 6, 7].map((d) => (
              <span key={d}>+{d}D</span>
            ))}
          </div>
        </div>
        <div className="timebar-key">
          <span className="timeline-key-dot" />
          CONJUNCTIONS
        </div>
      </div>
    </div>
  );
}

function CommandPalette({
  open,
  onOpenChange,
  catalog,
  threats,
  onSelect,
  onEvent,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  catalog: CatalogObject[];
  threats: Conjunction[];
  onSelect: (id: number) => void;
  onEvent: (id: string) => void;
}) {
  const [query, setQuery] = useState('');
  const search = useDeferredValue(query);
  const [answer, setAnswer] = useState('');
  const [working, setWorking] = useState(false);
  const [error, setError] = useState('');
  const results = useMemo(
    () =>
      catalog
        .filter(
          (o) =>
            !search ||
            o.name.toLowerCase().includes(search.toLowerCase()) ||
            String(o.noradId).includes(search),
        )
        .slice(0, 7),
    [catalog, search],
  );
  const ask = async () => {
    if (!query.trim() || working) return;
    setAnswer('');
    setError('');
    setWorking(true);
    try {
      await api.ask(query, (token) => setAnswer((a) => a + token));
    } catch {
      setError('Sentinel is unavailable. Try again or search the catalog.');
    } finally {
      setWorking(false);
    }
  };
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="command-palette">
          <Dialog.Title className="sr-only">Search or ask Sentinel</Dialog.Title>
          <Dialog.Description className="sr-only">
            Search catalog objects, open a conjunction, or submit a plain English question.
          </Dialog.Description>
          <div className="command-input">
            <Icon name="search" size={21} />
            <input
              autoFocus
              placeholder="Search an object, NORAD ID, or ask a question…"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setAnswer('');
                setError('');
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void ask();
              }}
            />
            <Dialog.Close className="icon-button" aria-label="Close search">
              <Icon name="close" />
            </Dialog.Close>
          </div>
          <div className="command-results">
            <div className="label-line">
              {query ? 'CATALOG MATCHES' : 'QUICK ACCESS · OBJECT CATALOG'}
            </div>
            {results.length ? (
              results.map((o) => (
                <button className="command-row" key={o.noradId} onClick={() => onSelect(o.noradId)}>
                  <Icon name="satellite" size={17} />
                  <span>
                    {o.name}
                    <small>
                      {o.type.replace('_', ' ')} · NORAD {o.noradId}
                    </small>
                  </span>
                  <Icon name="arrow" size={16} />
                </button>
              ))
            ) : (
              <p className="muted">No matching objects. Ask Sentinel about your question below.</p>
            )}
            {!query && (
              <>
                <div className="label-line command-section-label">ACTIVE CONJUNCTIONS</div>
                {threats.slice(0, 2).map((c) => (
                  <button className="command-row" key={c.id} onClick={() => onEvent(c.id)}>
                    <span className={`risk-badge ${c.risk}`}>{c.risk}</span>
                    <span>
                      {c.primary.name} × {c.secondary.name}
                    </span>
                    <Icon name="chevron" size={14} />
                  </button>
                ))}
              </>
            )}
            {query && (
              <button className="command-ask" onClick={() => void ask()} disabled={working}>
                <span className="sentinel-mark">S</span>
                {working ? 'Sentinel is analyzing…' : `Ask Sentinel: “${query}”`}
                <Icon name="arrow" size={17} />
              </button>
            )}
            {(answer || working) && (
              <div className="ask-answer" aria-live="polite">
                <div className="brief-label">
                  SENTINEL RESPONSE {isMockMode ? '· SAMPLE ANSWER' : ''}
                </div>
                <p>
                  {answer}
                  {working && <span className="typing-cursor" />}
                </p>
                {!working && REFUSAL.test(answer) && (
                  <span
                    className="refused-chip"
                    title="Sentinel answers only from computed screening data and does not guess."
                  >
                    Refused to guess · answers only from computed data
                  </span>
                )}
                <small>
                  {isMockMode
                    ? 'Simulated response. Connect the backend for Amazon Bedrock answers.'
                    : 'Generated by the configured backend. Verify operational decisions.'}
                </small>
              </div>
            )}
            {error && (
              <p className="error-text" role="alert">
                {error}
              </p>
            )}
          </div>
          <div className="command-footer">
            <span>Objects remain accessible without the globe.</span>
            <kbd>ESC</kbd>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function Modal({
  open,
  onOpenChange,
  title,
  description,
  children,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="modal">
          <Dialog.Title>{title}</Dialog.Title>
          <Dialog.Description>{description}</Dialog.Description>
          <Dialog.Close className="modal-close icon-button" aria-label="Close dialog">
            <Icon name="close" />
          </Dialog.Close>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
function Intro({ onSkip, objectCount }: { onSkip: () => void; objectCount: number }) {
  const [count, setCount] = useState(0);
  useEffect(() => {
    let raf = 0;
    const start = performance.now();
    function update(now: number) {
      const p = Math.min(1, (now - start) / 5400);
      setCount(Math.round(objectCount * (1 - (1 - p) ** 3)));
      if (p < 1) raf = requestAnimationFrame(update);
    }
    raf = requestAnimationFrame(update);
    return () => cancelAnimationFrame(raf);
  }, [objectCount]);
  return (
    <div className="intro-overlay">
      <div className="intro-brand">
        ORBIT<span>SENTINEL</span>
        <small>ORBITAL INTELLIGENCE</small>
      </div>
      <button className="intro-skip" onClick={onSkip}>
        Skip intro
        <Icon name="arrow" size={16} />
      </button>
      <div className="intro-copy">
        <span>ONE PLANET. A SHARED RESPONSIBILITY.</span>
        <strong>{compact(count)}</strong>
        <p>objects. Every orbit tells a story.</p>
        <div className="intro-progress">
          <i />
        </div>
      </div>
      <span className="intro-footer">ESTABLISHING ORBITAL AWARENESS</span>
    </div>
  );
}

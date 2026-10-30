import { Component, Suspense, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { CameraControls, Html, Line, Stats } from '@react-three/drei';
import { ACESFilmicToneMapping, BufferAttribute, BufferGeometry, DirectionalLight, Quaternion, SRGBColorSpace, Vector3 } from 'three';
import type CameraControlsImpl from 'camera-controls';
import { useCatalog } from '../api/hooks';
import type { CatalogObject, CascadeResult, Conjunction } from '../api/types';
import { useSimStore } from '../sim/store';
import Earth, { EarthFallback, solarDirection } from './Earth';
import ObjectCloud, { type LayerVisibility, type OrbitRegime, type PositionBuffers } from './ObjectCloud';
import { Encounter, SelectedObject, objectPositionAt } from './OrbitTrails';
import DebrisCascade from './DebrisCascade';
import './scene.css';

const EMPTY_CATALOG: CatalogObject[] = [];
const CAMERA_SETTINGS = { position: [0, 0.9, 4.3] as [number, number, number], fov: 40, near: 0.01, far: 180 };

export interface OrbitalSceneProps {
  mode: 'mission' | 'conjunction' | 'negotiator' | 'cascade';
  selectedId: number | null;
  conjunction?: Conjunction;
  cascade?: CascadeResult;
  cascadeYear: number;
  layers: LayerVisibility;
  regime: OrbitRegime;
  density: boolean;
  quality: 'high' | 'low';
  focusNonce: number;
  onSelect: (id: number | null) => void;
  replayProgress?: number;
  previewBurn?: boolean;
  introActive?: boolean;
}

class SceneBoundary extends Component<{ children: ReactNode; fallback?: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() { return this.state.failed ? this.props.fallback ?? <div className="scene-fallback"><div /><span>3D view unavailable</span><small>Object search and threat analysis are still available.</small></div> : this.props.children; }
}

function Starfield({ quality }: { quality: 'high' | 'low' }) {
  const geometry = useMemo(() => {
    const count = quality === 'high' ? 12000 : 4000;
    const positions = new Float32Array(count * 3), colors = new Float32Array(count * 3);
    let seed = 137;
    const random = () => { seed = Math.imul(seed, 1664525) + 1013904223 | 0; return (seed >>> 0) / 4294967296; };
    for (let i = 0; i < count; i++) {
      const y = random() * 2 - 1, angle = random() * Math.PI * 2, horizontal = Math.sqrt(1 - y * y);
      positions[i * 3] = Math.cos(angle) * horizontal * 90; positions[i * 3 + 1] = y * 90; positions[i * 3 + 2] = Math.sin(angle) * horizontal * 90;
      const magnitude = 0.13 + Math.pow(random(), 6) * 0.73;
      colors[i * 3] = magnitude * (0.85 + random() * 0.15); colors[i * 3 + 1] = magnitude * 0.94; colors[i * 3 + 2] = magnitude;
    }
    const result = new BufferGeometry(); result.setAttribute('position', new BufferAttribute(positions, 3)); result.setAttribute('color', new BufferAttribute(colors, 3)); return result;
  }, [quality]);
  useEffect(() => () => geometry.dispose(), [geometry]);
  return <points geometry={geometry} raycast={() => null}><pointsMaterial size={0.13} vertexColors sizeAttenuation transparent opacity={0.72} depthWrite={false} /></points>;
}

function SolarLighting() {
  const light = useRef<DirectionalLight>(null);
  const direction = useMemo(() => new Vector3(), []);
  useFrame(() => { if (light.current) light.current.position.copy(solarDirection(useSimStore.getState().timeMs, direction)).multiplyScalar(12); });
  return <><ambientLight intensity={0.06} /><directionalLight ref={light} position={[5, 4, 6]} intensity={2.1} color="#e4eeff" /></>;
}

function DensityShells() {
  return <>{[1.086, 1.128].map((radius, i) => <mesh key={radius}><sphereGeometry args={[radius, 48, 32]} /><meshBasicMaterial color={i === 0 ? '#ff873f' : '#6bbaff'} transparent opacity={0.035} depthWrite={false} wireframe /></mesh>)}</>;
}

function DrawCallReadout() {
  const { gl } = useThree();
  const element = useRef<HTMLDivElement>(null);
  const last = useRef(0);
  useFrame(({ clock }) => {
    if (element.current && clock.elapsedTime - last.current > 0.5) {
      element.current.textContent = `${gl.info.render.calls} draw calls · ${gl.info.render.points.toLocaleString()} points`;
      last.current = clock.elapsedTime;
    }
  });
  return <Html fullscreen style={{ pointerEvents: 'none' }}><div ref={element} className="scene-diagnostics" /></Html>;
}

function RegimeRing() {
  const points = useMemo(() => Array.from({ length: 181 }, (_, index) => { const angle = index / 180 * Math.PI * 2; return new Vector3(Math.cos(angle) * 1.28, 0, Math.sin(angle) * 1.28); }), []);
  return <Line points={points} color="#52677e" lineWidth={0.65} transparent opacity={0.19} dashed dashSize={0.025} gapSize={0.045} />;
}

function CameraDirector({ props, catalog, idToIndex, buffers, controls }: { props: OrbitalSceneProps; catalog: CatalogObject[]; idToIndex: Map<number, number>; buffers: React.MutableRefObject<PositionBuffers>; controls: React.RefObject<CameraControlsImpl> }) {
  const { camera, size } = useThree();
  const conjunctionId = props.conjunction?.id;
  const conjunctionPrimaryId = props.conjunction?.primary.noradId;
  const conjunctionTca = props.conjunction?.tca;
  const selectedIdRef = useRef(props.selectedId);
  selectedIdRef.current = props.selectedId;
  const lastFocusNonce = useRef(0);
  const userDragged = useRef(false);
  const followed = useRef({ id: null as number | null, position: new Vector3(), camera: new Vector3(), target: new Vector3() });
  const tween = useRef({ startTime: 0, duration: 2400, active: false, start: new Vector3(), end: new Vector3(), startTarget: new Vector3(), endTarget: new Vector3(), rotation: new Quaternion(), identity: new Quaternion(), direction: new Vector3(), position: new Vector3(), target: new Vector3() });
  const introDeadline = useRef(performance.now() + 6000);
  useEffect(() => {
    const controller = controls.current;
    if (!controller) return;
    const interrupt = () => { tween.current.active = false; userDragged.current = true; };
    controller.addEventListener('controlstart', interrupt);
    return () => controller.removeEventListener('controlstart', interrupt);
  }, [controls]);
  useEffect(() => {
    if (!controls.current) return;
    const animation = tween.current;
    const selectedId = selectedIdRef.current;
    const focusRequested = lastFocusNonce.current !== props.focusNonce;
    lastFocusNonce.current = props.focusNonce;
    userDragged.current = false;
    followed.current.id = null;
    const sun = solarDirection(useSimStore.getState().timeMs);
    const overview = sun.applyAxisAngle(new Vector3(0, 1, 0), 0.8).add(new Vector3(0, 0.22, 0)).normalize();
    let end = overview.clone().multiplyScalar(size.width < 768 ? 4.55 : 4.15);
    const target = new Vector3(0, 0, 0);
    const focusId = props.mode !== 'mission' && conjunctionPrimaryId ? conjunctionPrimaryId : selectedId;
    const index = idToIndex.get(focusId ?? -1) ?? -1;
    if ((props.mode === 'conjunction' || props.mode === 'negotiator') && index >= 0 && buffers.current.current.length > index * 3 + 2) {
      const coordinates = buffers.current.current;
      const selected = conjunctionTca ? objectPositionAt(catalog[index], new Date(conjunctionTca).getTime()) ?? new Vector3(coordinates[index * 3], coordinates[index * 3 + 1], coordinates[index * 3 + 2]) : new Vector3(coordinates[index * 3], coordinates[index * 3 + 1], coordinates[index * 3 + 2]);
      end = selected.clone().normalize().addScaledVector(overview, 0.5).normalize().multiplyScalar(props.mode === 'negotiator' ? 4.7 : 3.2);
      target.copy(selected).multiplyScalar(0.50);
    } else if (props.mode === 'mission' && selectedId && index >= 0) {
      const positions = buffers.current.current;
      const selected = new Vector3(positions[index * 3], positions[index * 3 + 1], positions[index * 3 + 2]);
      end = selected.clone().normalize().multiplyScalar(Math.max(2.15, selected.length() + 0.95)).addScaledVector(overview, 0.35);
      target.copy(selected).multiplyScalar(0.82);
    }
    if (props.mode === 'cascade') end.copy(overview).multiplyScalar(4.1);
    if (props.introActive && animation.startTime === 0) controls.current.setLookAt(overview.x * 11, overview.y * 11, overview.z * 11, 0, 0, 0, false);
    controls.current.getPosition(animation.start);
    controls.current.getTarget(animation.startTarget);
    animation.end.copy(end); animation.endTarget.copy(target);
    animation.rotation.setFromUnitVectors(animation.start.clone().normalize(), animation.end.clone().normalize());
    animation.startTime = performance.now();
    animation.duration = window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 100 : props.introActive ? Math.max(100, introDeadline.current - performance.now()) : props.mode === 'mission' && selectedId ? 1200 : focusRequested ? 950 : 850;
    animation.active = true;
    return () => { animation.active = false; };
  }, [props.mode, props.selectedId, props.focusNonce, conjunctionId, conjunctionPrimaryId, conjunctionTca, props.introActive, catalog, idToIndex, buffers, controls, size.width]);
  useFrame(() => {
    const animation = tween.current;
    if (!controls.current) return;
    if (!animation.active) {
      if (props.mode === 'mission' && props.selectedId) {
        const index = idToIndex.get(props.selectedId) ?? -1;
        const coordinates = buffers.current.current;
        if (index >= 0 && coordinates.length > index * 3 + 2) {
          const follow = followed.current;
          const x = coordinates[index * 3], y = coordinates[index * 3 + 1], z = coordinates[index * 3 + 2];
          if (follow.id === props.selectedId) {
            const dx = (x - follow.position.x) * 0.82, dy = (y - follow.position.y) * 0.82, dz = (z - follow.position.z) * 0.82;
            if (dx || dy || dz) {
              controls.current.getPosition(follow.camera);
              controls.current.getTarget(follow.target);
              controls.current.setLookAt(follow.camera.x + dx, follow.camera.y + dy, follow.camera.z + dz, follow.target.x + dx, follow.target.y + dy, follow.target.z + dz, false);
            }
          }
          follow.position.set(x, y, z);
          follow.id = props.selectedId;
        }
      }
      if (props.mode === 'mission' && props.selectedId && !userDragged.current && !window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        const phase = performance.now() * 0.00018;
        const offset = Math.sin(phase) * 0.00045;
        controls.current.rotate(offset, 0, false);
      }
      return;
    }
    const raw = Math.min((performance.now() - animation.startTime) / animation.duration, 1);
    const progress = raw * raw * raw * (raw * (raw * 6 - 15) + 10);
    // Rotate the viewing direction on a sphere instead of interpolating a chord through Earth.
    animation.identity.identity().slerp(animation.rotation, progress);
    animation.direction.copy(animation.start).normalize().applyQuaternion(animation.identity);
    const radius = animation.start.length() + (animation.end.length() - animation.start.length()) * progress;
    animation.position.copy(animation.direction).multiplyScalar(Math.max(radius, 2.2));
    animation.target.lerpVectors(animation.startTarget, animation.endTarget, progress);
    controls.current.setLookAt(animation.position.x, animation.position.y, animation.position.z, animation.target.x, animation.target.y, animation.target.z, false);
    camera.updateMatrixWorld();
    if (raw === 1) animation.active = false;
  });
  return null;
}

function ObjectPicker({ catalog, buffers, layers, regime, onSelect, onHover }: { catalog: CatalogObject[]; buffers: React.MutableRefObject<PositionBuffers>; layers: LayerVisibility; regime: OrbitRegime; onSelect: (id: number | null) => void; onHover: (index: number, x: number, y: number) => void }) {
  const { gl, camera, size } = useThree();
  const grid = useRef(new Map<number, number[]>());
  const screen = useMemo(() => new Float32Array(catalog.length * 2), [catalog]);
  const lastBuild = useRef(-1), pointer = useRef({ x: -100, y: -100 }), lastHovered = useRef(-1);
  const vector = useMemo(() => new Vector3(), []);
  const columns = Math.ceil(size.width / 16) + 1;
  useFrame(({ clock }) => {
    if (clock.elapsedTime - lastBuild.current < 0.35 || !catalog.length) return;
    lastBuild.current = clock.elapsedTime;
    grid.current.clear();
    const positions = buffers.current.current;
    const cx = camera.position.x, cy = camera.position.y, cz = camera.position.z;
    for (let index = 0; index < catalog.length; index++) {
      const object = catalog[index];
      if ((object.type === 'PAYLOAD' && !layers.payload) || (object.type === 'DEBRIS' && !layers.debris) || (object.type === 'ROCKET_BODY' && !layers.rocket)) continue;
      const px = positions[index * 3], py = positions[index * 3 + 1], pz = positions[index * 3 + 2];
      const radius = Math.hypot(px, py, pz);
      if (regime !== 'ALL' && (regime === 'LEO' ? radius >= 1.35 : regime === 'GEO' ? radius <= 6 : radius < 1.35 || radius > 6)) continue;
      const dx = px - cx, dy = py - cy, dz = pz - cz, t = -(cx * dx + cy * dy + cz * dz) / (dx * dx + dy * dy + dz * dz);
      if (t > 0 && t < 1 && Math.hypot(cx + dx * t, cy + dy * t, cz + dz * t) < 1) continue;
      vector.set(px, py, pz).project(camera);
      if (vector.z < -1 || vector.z > 1 || Math.abs(vector.x) > 1 || Math.abs(vector.y) > 1) continue;
      const x = (vector.x + 1) * size.width / 2, y = (1 - vector.y) * size.height / 2;
      screen[index * 2] = x; screen[index * 2 + 1] = y;
      const key = Math.floor(x / 16) + Math.floor(y / 16) * columns;
      const cell = grid.current.get(key);
      if (cell) cell.push(index); else grid.current.set(key, [index]);
    }
  });
  useEffect(() => {
    const canvas = gl.domElement;
    let frame = 0;
    let pointerDown = { x: 0, y: 0 };
    const locate = () => {
      frame = 0;
      let closest = -1, minimum = 64;
      const gx = Math.floor(pointer.current.x / 16), gy = Math.floor(pointer.current.y / 16);
      for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
        const cell = grid.current.get(gx + dx + (gy + dy) * columns);
        if (!cell) continue;
        for (const index of cell) {
          const distance = (screen[index * 2] - pointer.current.x) ** 2 + (screen[index * 2 + 1] - pointer.current.y) ** 2;
          if (distance < minimum) { minimum = distance; closest = index; }
        }
      }
      if (lastHovered.current !== closest) {
        lastHovered.current = closest;
        canvas.style.cursor = closest >= 0 ? 'pointer' : 'grab';
      }
      onHover(closest, pointer.current.x, pointer.current.y);
    };
    const move = (event: PointerEvent) => { const bounds = canvas.getBoundingClientRect(); pointer.current.x = event.clientX - bounds.left; pointer.current.y = event.clientY - bounds.top; if (!frame) frame = requestAnimationFrame(locate); };
    const leave = () => { lastHovered.current = -1; canvas.style.cursor = 'grab'; onHover(-1, 0, 0); };
    const down = (event: PointerEvent) => { pointerDown = { x: event.clientX, y: event.clientY }; };
    const click = (event: MouseEvent) => {
      const bounds = canvas.getBoundingClientRect();
      pointer.current.x = event.clientX - bounds.left; pointer.current.y = event.clientY - bounds.top;
      locate();
      if (Math.hypot(event.clientX - pointerDown.x, event.clientY - pointerDown.y) < 5) onSelect(lastHovered.current >= 0 ? catalog[lastHovered.current].noradId : null);
    };
    canvas.addEventListener('pointermove', move); canvas.addEventListener('pointerleave', leave); canvas.addEventListener('pointerdown', down); canvas.addEventListener('click', click);
    return () => { cancelAnimationFrame(frame); canvas.removeEventListener('pointermove', move); canvas.removeEventListener('pointerleave', leave); canvas.removeEventListener('pointerdown', down); canvas.removeEventListener('click', click); };
  }, [gl, catalog, columns, screen, buffers, onSelect, onHover]);
  return null;
}

function SceneContents({ props, onWorkerError, onHover, hoveredId, debug }: { props: OrbitalSceneProps; onWorkerError: (value: string) => void; onHover: (index: number, x: number, y: number) => void; hoveredId: number | null; debug: boolean }) {
  const catalogQuery = useCatalog();
  const catalog = catalogQuery.data ?? EMPTY_CATALOG;
  const idToIndex = useMemo(() => new Map(catalog.map((object, index) => [object.noradId, index])), [catalog]);
  const controls = useRef<CameraControlsImpl>(null);
  const buffers = useRef<PositionBuffers>({ current: new Float32Array(), previous: new Float32Array(), updatedAt: 0 });
  const currentId = props.selectedId ?? (props.mode === 'conjunction' || props.mode === 'negotiator' ? props.conjunction?.primary.noradId ?? null : null);
  const [displayId, setDisplayId] = useState<number | null>(currentId);
  useEffect(() => {
    if (currentId !== null) { setDisplayId(currentId); return; }
    const timer = window.setTimeout(() => setDisplayId(null), 450);
    return () => window.clearTimeout(timer);
  }, [currentId]);
  const selectedIndex = idToIndex.get(displayId ?? -1) ?? -1;
  const hoveredIndex = idToIndex.get(hoveredId ?? -1) ?? -1;
  const primaryIndex = idToIndex.get(props.conjunction?.primary.noradId ?? -1) ?? -1;
  const primary = primaryIndex >= 0 ? catalog[primaryIndex] : undefined;
  return <>
    <color attach="background" args={['#05070d']} />
    <SolarLighting />
    <Starfield quality={props.quality} />
    <SceneBoundary fallback={<EarthFallback />}><Earth quality={props.quality} /></SceneBoundary>
    <RegimeRing />
    {catalog.length > 0 && <ObjectCloud catalog={catalog} layers={props.layers} regime={props.regime} buffers={buffers} selectedIndex={currentId === null ? -1 : selectedIndex} hoveredIndex={hoveredIndex} onWorkerError={onWorkerError} />}
    {props.density && <DensityShells />}
    {selectedIndex >= 0 && <SelectedObject key={displayId} object={catalog[selectedIndex]} index={selectedIndex} buffers={buffers} exiting={currentId === null} />}
    {props.conjunction && primary && props.mode !== 'mission' && <Encounter conjunction={props.conjunction} primary={primary} replayProgress={props.replayProgress} previewBurn={props.previewBurn} />}
    {props.cascade && props.mode === 'cascade' && <DebrisCascade result={props.cascade} year={props.cascadeYear} />}
    <CameraControls ref={controls} minDistance={1.7} maxDistance={14} smoothTime={0.3} draggingSmoothTime={0.12} dollySpeed={0.6} />
    <CameraDirector props={props} catalog={catalog} idToIndex={idToIndex} buffers={buffers} controls={controls} />
    <ObjectPicker catalog={catalog} buffers={buffers} layers={props.layers} regime={props.regime} onSelect={props.onSelect} onHover={onHover} />
    {debug && <><Stats className="scene-stats" /><DrawCallReadout /></>}
  </>;
}

export default function OrbitalScene(props: OrbitalSceneProps) {
  const [workerError, setWorkerError] = useState('');
  const [debug, setDebug] = useState(false);
  const [visible, setVisible] = useState(!document.hidden);
  const [hover, setHover] = useState<{ index: number; x: number; y: number }>({ index: -1, x: 0, y: 0 });
  const catalog = useCatalog().data;
  const onHover = useCallback((index: number, x: number, y: number) => setHover(previous => previous.index === index && Math.abs(previous.x - x) < 20 && Math.abs(previous.y - y) < 20 ? previous : { index, x, y }), []);
  const reportError = useCallback((message: string) => setWorkerError(message), []);
  const rendererSettings = useMemo(() => ({ antialias: true, alpha: false, powerPreference: props.quality === 'high' ? 'high-performance' as const : 'low-power' as const }), [props.quality]);
  useEffect(() => {
    const visibility = () => setVisible(!document.hidden);
    const key = (event: KeyboardEvent) => { if (import.meta.env.DEV && event.shiftKey && event.key.toLowerCase() === 'd') setDebug(value => !value); };
    document.addEventListener('visibilitychange', visibility); window.addEventListener('keydown', key);
    return () => { document.removeEventListener('visibilitychange', visibility); window.removeEventListener('keydown', key); };
  }, []);
  return <div className="orbital-scene" aria-label="Interactive Earth and orbital catalog. Use object search for a text alternative.">
    <SceneBoundary>
      <Canvas camera={CAMERA_SETTINGS} dpr={props.quality === 'high' ? [1, 1.75] : 1} frameloop={visible ? 'always' : 'never'} gl={rendererSettings} onCreated={({ gl }) => { gl.toneMapping = ACESFilmicToneMapping; gl.toneMappingExposure = 1.18; gl.outputColorSpace = SRGBColorSpace; gl.domElement.setAttribute('role', 'img'); gl.domElement.setAttribute('aria-label', 'Earth orbit visualization. Drag to rotate, scroll to zoom. Click a catalog dot for object information.'); }}>
        <Suspense fallback={null}><SceneContents props={props} onWorkerError={reportError} onHover={onHover} hoveredId={catalog?.[hover.index]?.noradId ?? null} debug={debug} /></Suspense>
      </Canvas>
    </SceneBoundary>
    <div className="scene-vignette" />
    {hover.index >= 0 && catalog?.[hover.index] && hover.x > 0 && <div className="scene-hover-label" style={{ left: hover.x + 16, top: hover.y - 12 }} role="status">{catalog[hover.index].name}<small>NORAD {catalog[hover.index].noradId}</small></div>}
    {workerError && <div className="scene-worker-notice" role="status">Propagation paused · showing last available positions</div>}
  </div>;
}

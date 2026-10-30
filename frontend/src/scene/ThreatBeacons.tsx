import { useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import { Billboard, Line } from '@react-three/drei';
import { Color, Group, MathUtils, Mesh, MeshBasicMaterial, Vector3 } from 'three';
import type { Line2 } from 'three-stdlib';
import { useConjunctions } from '../api/hooks';
import type { Conjunction } from '../api/types';
import { useReducedMotion } from '../ui/useReducedMotion';
import { readDisplayedPosition, type PositionBuffers } from './ObjectCloud';

const noPick = () => null;
const SEGMENTS = 32;

function ThreatBeacon({ event, primaryIndex, secondaryIndex, buffers }: {
  event: Conjunction; primaryIndex: number; secondaryIndex: number;
  buffers: React.MutableRefObject<PositionBuffers>;
}) {
  const root = useRef<Group>(null);
  const beacon = useRef<Group>(null);
  const ring = useRef<Mesh>(null);
  const arc = useRef<Line2>(null);
  const reduced = useReducedMotion();
  const color = useMemo(() => new Color(event.risk === 'critical' ? '#ff5d66' : '#f2c14e').multiplyScalar(6), [event.risk]);
  const initial = useMemo(() => [new Vector3(), new Vector3(0, 0.001, 0)], []);
  const state = useMemo(() => ({
    primary: new Vector3(), secondary: new Vector3(), a: new Vector3(), b: new Vector3(),
    axis: new Vector3(), direction: new Vector3(), positions: new Float32Array((SEGMENTS + 1) * 3),
    lastUpdate: -Infinity,
  }), []);
  useFrame(({ clock }) => {
    if (!root.current || !beacon.current || !ring.current || !arc.current) return;
    const ready = buffers.current.current.length > Math.max(primaryIndex, secondaryIndex) * 3 + 2;
    root.current.visible = ready;
    if (!ready) return;
    readDisplayedPosition(buffers.current, primaryIndex, state.primary);
    readDisplayedPosition(buffers.current, secondaryIndex, state.secondary);
    if (![state.primary.x, state.primary.y, state.primary.z, state.secondary.x, state.secondary.y, state.secondary.z].every(Number.isFinite)) {
      root.current.visible = false;
      return;
    }
    beacon.current.position.copy(state.primary);
    // One gentle pulse every 2.8 seconds; reduced motion stays fully static.
    const pulse = reduced ? 0 : Math.sin(clock.elapsedTime * Math.PI * 2 / 2.8);
    ring.current.scale.setScalar(1 + pulse * 0.18);
    (ring.current.material as MeshBasicMaterial).opacity = 0.65 + pulse * 0.15;
    // Throttle decorative arc updates to 10 Hz; catalog interpolation/picking is unchanged.
    if (clock.elapsedTime - state.lastUpdate < 0.1) return;
    state.lastUpdate = clock.elapsedTime;
    const r1 = state.primary.length(), r2 = state.secondary.length();
    if (r1 < 1 || r2 < 1) { root.current.visible = false; return; }
    state.a.copy(state.primary).normalize();
    state.b.copy(state.secondary).normalize();
    const angle = Math.acos(MathUtils.clamp(state.a.dot(state.b), -1, 1));
    state.axis.crossVectors(state.a, state.b);
    if (state.axis.lengthSq() < 1e-8) {
      state.axis.set(0, 1, 0).cross(state.a);
      if (state.axis.lengthSq() < 1e-8) state.axis.set(1, 0, 0).cross(state.a);
    }
    state.axis.normalize();
    for (let i = 0; i <= SEGMENTS; i++) {
      const t = i / SEGMENTS;
      // This raised visual link identifies the forecast pair; it is not an orbit/burn path.
      const radius = MathUtils.lerp(r1, r2, t) + Math.sin(Math.PI * t) * Math.min(0.28, angle * 0.2);
      state.direction.copy(state.a).applyAxisAngle(state.axis, angle * t).multiplyScalar(radius);
      state.positions[i * 3] = state.direction.x;
      state.positions[i * 3 + 1] = state.direction.y;
      state.positions[i * 3 + 2] = state.direction.z;
    }
    arc.current.geometry.setPositions(state.positions);
    arc.current.computeLineDistances();
  });
  return <group ref={root} visible={false}>
    <group ref={beacon}>
      <Billboard>
        <mesh ref={ring} raycast={noPick}>
          <ringGeometry args={[0.038, 0.044, 40]} />
          <meshBasicMaterial color={color} toneMapped={false} transparent opacity={0.7} depthWrite={false} />
        </mesh>
        <mesh raycast={noPick}>
          <ringGeometry args={[0.018, 0.022, 32]} />
          <meshBasicMaterial color={color} toneMapped={false} transparent opacity={0.65} depthWrite={false} />
        </mesh>
      </Billboard>
    </group>
    <Line ref={arc} points={initial} color={color} lineWidth={0.8} transparent opacity={0.5} toneMapped={false} depthWrite={false} raycast={noPick} />
  </group>;
}

export default function ThreatBeacons({ idToIndex, buffers }: {
  idToIndex: Map<number, number>; buffers: React.MutableRefObject<PositionBuffers>;
}) {
  // Same query key as Mission Control: React Query shares the existing cached request.
  const { data } = useConjunctions();
  const events = useMemo(() => (data ?? [])
    .filter(event => event.risk !== 'watch' && idToIndex.has(event.primary.noradId) && idToIndex.has(event.secondary.noradId))
    .sort((a, b) => Number(b.risk === 'critical') - Number(a.risk === 'critical') || b.pc - a.pc)
    .slice(0, 8), [data, idToIndex]);
  return <>{events.map(event => <ThreatBeacon key={event.id} event={event}
    primaryIndex={idToIndex.get(event.primary.noradId)!} secondaryIndex={idToIndex.get(event.secondary.noradId)!} buffers={buffers} />)}</>;
}

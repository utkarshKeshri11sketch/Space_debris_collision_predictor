import { useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import { DoubleSide, Group, MathUtils } from 'three';
import type { CatalogObject } from '../api/types';

type Variant = 'iss' | 'starlink' | 'cubesat' | 'satellite' | 'rocket' | 'debris';

export function modelVariant(object: CatalogObject): Variant {
  if (object.type === 'DEBRIS') return 'debris';
  if (object.type === 'ROCKET_BODY') return 'rocket';
  if (object.noradId === 25544 || /(?:^|\W)ISS(?:\W|$)/i.test(object.name)) return 'iss';
  if (/STARLINK/i.test(object.name)) return 'starlink';
  if (/CUBESAT|CUBE\s?SAT|NANOSAT/i.test(object.name)) return 'cubesat';
  return 'satellite';
}

function Panel({ size = [0.25, 0.11] }: { size?: [number, number] }) {
  return <group>
    <mesh><boxGeometry args={[size[0], size[1], 0.006]} /><meshStandardMaterial color="#192638" metalness={0.48} roughness={0.32} side={DoubleSide} /></mesh>
    <mesh position={[0, 0, 0.004]}><planeGeometry args={[size[0] * 0.9, size[1] * 0.82]} /><meshPhysicalMaterial color="#122d52" metalness={0.64} roughness={0.22} clearcoat={0.75} side={DoubleSide} /></mesh>
    {[-0.25, 0, 0.25].map(x => <mesh key={x} position={[x * size[0] * 2.7, 0, 0.005]}><boxGeometry args={[0.0015, size[1] * 0.84, 0.001]} /><meshBasicMaterial color="#7ca4bf" transparent opacity={0.48} /></mesh>)}
  </group>;
}

function Body({ compact = false }: { compact?: boolean }) {
  return <group>
    <mesh><boxGeometry args={compact ? [0.065, 0.065, 0.065] : [0.12, 0.095, 0.09]} /><meshStandardMaterial color="#b6bec8" metalness={0.78} roughness={0.29} /></mesh>
    <mesh position={[0, 0, 0.047]}><boxGeometry args={compact ? [0.047, 0.047, 0.002] : [0.095, 0.07, 0.002]} /><meshStandardMaterial color="#a49a80" metalness={0.8} roughness={0.35} /></mesh>
  </group>;
}

export default function SelectedModel({ object, exiting, reduced }: { object: CatalogObject; exiting: boolean; reduced: boolean }) {
  const variant = useMemo(() => modelVariant(object), [object]);
  const root = useRef<Group>(null);
  const left = useRef<Group>(null);
  const right = useRef<Group>(null);
  const single = useRef<Group>(null);
  const elapsed = useRef(0);
  const progress = useRef(0);
  useFrame((_, delta) => {
    elapsed.current += delta;
    const target = exiting ? 0 : 1;
    progress.current = MathUtils.damp(progress.current, target, reduced ? 25 : 7, delta);
    const t = progress.current;
    // A small, damped overshoot gives the deployment a spring feel without a second animation loop.
    const overshoot = reduced || exiting ? 0 : Math.sin(Math.min(elapsed.current * 9, Math.PI * 2)) * Math.exp(-elapsed.current * 4) * 0.14;
    if (root.current) {
      root.current.scale.setScalar(Math.max(0.001, t + overshoot));
      root.current.rotation.y += reduced ? 0 : delta * (variant === 'debris' || variant === 'rocket' ? 0.18 : 0.045);
      if (variant === 'debris' || variant === 'rocket') root.current.rotation.z += reduced ? 0 : delta * 0.09;
    }
    const unfold = reduced ? t : MathUtils.smoothstep(Math.max(0, elapsed.current - 0.28), 0, 0.9) * t;
    if (left.current) left.current.rotation.y = -Math.PI * 0.48 * (1 - unfold);
    if (right.current) right.current.rotation.y = Math.PI * 0.48 * (1 - unfold);
    if (single.current) single.current.rotation.x = Math.PI * 0.48 * (1 - unfold);
  });

  return <group ref={root} scale={0.001}>
    {variant === 'debris' ? <>
      <mesh rotation={[0.3, 0.5, 0.2]}><tetrahedronGeometry args={[0.105, 0]} /><meshStandardMaterial color="#a06039" flatShading metalness={0.58} roughness={0.44} /></mesh>
      <mesh position={[0.06, -0.03, 0.03]} rotation={[0.8, 0.2, 0.9]}><tetrahedronGeometry args={[0.054, 0]} /><meshStandardMaterial color="#de8750" flatShading metalness={0.52} roughness={0.48} /></mesh>
      <pointLight color="#ff8a3d" intensity={0.22} distance={0.6} />
    </> : variant === 'rocket' ? <>
      <mesh rotation={[Math.PI / 2, 0, 0]}><cylinderGeometry args={[0.058, 0.07, 0.32, 12]} /><meshStandardMaterial color="#aeb7c3" metalness={0.8} roughness={0.36} /></mesh>
      <mesh position={[0, 0, -0.18]} rotation={[Math.PI / 2, 0, 0]}><cylinderGeometry args={[0.035, 0.068, 0.08, 12, 1, true]} /><meshStandardMaterial color="#596575" metalness={0.83} roughness={0.4} side={DoubleSide} /></mesh>
      <mesh position={[0, 0, 0.18]}><coneGeometry args={[0.056, 0.06, 12]} /><meshStandardMaterial color="#d6dbe0" metalness={0.62} roughness={0.34} /></mesh>
    </> : variant === 'iss' ? <>
      <mesh><boxGeometry args={[0.52, 0.012, 0.016]} /><meshStandardMaterial color="#d0d8e0" metalness={0.8} roughness={0.32} /></mesh>
      {[-0.16, -0.06, 0.06, 0.16].map(x => <group key={x} position={[x, 0, 0]}><mesh rotation={[Math.PI / 2, 0, 0]}><cylinderGeometry args={[0.025, 0.025, 0.1, 12]} /><meshStandardMaterial color="#e2e6e9" metalness={0.72} roughness={0.34} /></mesh></group>)}
      {[-0.22, -0.13, 0.13, 0.22].map(x => <group key={x} position={[x, 0.082, 0]} rotation={[0, 0, 0.03]}><Panel size={[0.082, 0.15]} /></group>)}
      {[-0.22, -0.13, 0.13, 0.22].map(x => <group key={x} position={[x, -0.082, 0]}><Panel size={[0.082, 0.15]} /></group>)}
    </> : variant === 'starlink' ? <>
      <mesh><boxGeometry args={[0.19, 0.075, 0.018]} /><meshStandardMaterial color="#bbc4cb" metalness={0.72} roughness={0.31} /></mesh>
      <group ref={single} position={[0, 0.16, 0]}><Panel size={[0.17, 0.26]} /></group>
    </> : <>
      <Body compact={variant === 'cubesat'} />
      <group ref={left} position={[-0.16, 0, 0]}><Panel size={variant === 'cubesat' ? [0.11, 0.07] : [0.19, 0.11]} /></group>
      <group ref={right} position={[0.16, 0, 0]}><Panel size={variant === 'cubesat' ? [0.11, 0.07] : [0.19, 0.11]} /></group>
      {variant === 'satellite' && <group position={[0, 0.085, 0]}><mesh><cylinderGeometry args={[0.026, 0.015, 0.016, 16]} /><meshStandardMaterial color="#dde3e7" metalness={0.68} roughness={0.33} /></mesh><mesh position={[0, 0.032, 0]}><cylinderGeometry args={[0.002, 0.002, 0.05, 8]} /><meshStandardMaterial color="#c5cdd4" metalness={0.72} roughness={0.32} /></mesh></group>}
    </>}
  </group>;
}

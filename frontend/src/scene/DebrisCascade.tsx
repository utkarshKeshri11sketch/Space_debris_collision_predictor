import { useEffect, useMemo, useRef } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import { Billboard } from '@react-three/drei';
import { AdditiveBlending, BufferAttribute, BufferGeometry, Mesh, ShaderMaterial } from 'three';
import { gstime } from 'satellite.js';
import type { CascadeResult } from '../api/types';
import { useSimStore } from '../sim/store';
import vertex from './cascade.vert.glsl?raw';
import fragment from './cascade.frag.glsl?raw';

function seeded(seed: number) { return () => { seed |= 0; seed = seed + 0x6d2b79f5 | 0; let value = Math.imul(seed ^ seed >>> 15, 1 | seed); value = value + Math.imul(value ^ value >>> 7, 61 | value) ^ value; return ((value ^ value >>> 14) >>> 0) / 4294967296; }; }

function SecondaryCloud({ event, year, seed }: { event: CascadeResult['secondaryCollisions'][number]; year: number; seed: number }) {
  const { gl } = useThree();
  const material = useRef<ShaderMaterial>(null);
  const geometry = useMemo(() => {
    const random = seeded(seed), count = Math.min(event.fragments, 2000);
    const result = new BufferGeometry();
    const phase = new Float32Array(count), kick = new Float32Array(count), node = new Float32Array(count);
    for (let i = 0; i < count; i++) { phase[i] = random() * Math.PI * 2; kick[i] = Math.sqrt(-2 * Math.log(Math.max(random(), 0.00001))) * Math.cos(2 * Math.PI * random()) * 0.15; node[i] = random() * 2 - 1; }
    result.setAttribute('position', new BufferAttribute(new Float32Array(count * 3), 3));
    result.setAttribute('aPhase', new BufferAttribute(phase, 1)); result.setAttribute('aKick', new BufferAttribute(kick, 1)); result.setAttribute('aNode', new BufferAttribute(node, 1));
    return result;
  }, [event.fragments, seed]);
  const uniforms = useMemo(() => {
    const latitude = event.latDeg * Math.PI / 180;
    const inclination = Math.max(55, Math.abs(event.latDeg) + 12) * Math.PI / 180;
    const phase = Math.asin(Math.sin(latitude) / Math.sin(inclination));
    const longitudeFromNode = Math.atan2(Math.sin(phase) * Math.cos(inclination), Math.cos(phase));
    const node = event.lonDeg * Math.PI / 180 + gstime(new Date(useSimStore.getState().timeMs)) - longitudeFromNode;
    return { uYear: { value: 0 }, uRadius: { value: 1 + event.altKm / 6378.137 }, uInclination: { value: inclination }, uNode: { value: node }, uPhase: { value: phase }, uPixelRatio: { value: Math.min(gl.getPixelRatio(), 1.5) } };
  }, [event, gl]);
  useEffect(() => () => geometry.dispose(), [geometry]);
  useFrame(() => { if (material.current) material.current.uniforms.uYear.value = Math.max(0.001, year - event.year); });
  return <points geometry={geometry} frustumCulled={false} raycast={() => null}><shaderMaterial ref={material} vertexShader={vertex} fragmentShader={fragment} uniforms={uniforms} transparent depthWrite={false} blending={AdditiveBlending} /></points>;
}

export default function DebrisCascade({ result, year }: { result: CascadeResult; year: number }) {
  const { gl } = useThree();
  const material = useRef<ShaderMaterial>(null);
  const burst = useRef<Mesh>(null);
  const started = useRef(performance.now());
  const reduced = useMemo(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches, []);
  const data = useMemo(() => {
    const random = seeded(result.seed), count = Math.min(result.fragmentCount, 18000);
    const geometry = new BufferGeometry();
    const phases = new Float32Array(count), kicks = new Float32Array(count), nodes = new Float32Array(count);
    for (let i = 0; i < count; i++) {
      phases[i] = random() * Math.PI * 2;
      kicks[i] = Math.sqrt(-2 * Math.log(Math.max(random(), 0.00001))) * Math.cos(2 * Math.PI * random()) * result.spreadDvMs.sd / 100;
      nodes[i] = random() * 2 - 1;
    }
    geometry.setAttribute('position', new BufferAttribute(new Float32Array(count * 3), 3));
    geometry.setAttribute('aPhase', new BufferAttribute(phases, 1));
    geometry.setAttribute('aKick', new BufferAttribute(kicks, 1));
    geometry.setAttribute('aNode', new BufferAttribute(nodes, 1));
    const motion = Number(result.parent.omm.MEAN_MOTION) * Math.PI * 2 / 86400;
    const phase = (Number(result.parent.omm.MEAN_ANOMALY) + Number(result.parent.omm.ARG_OF_PERICENTER ?? 0)) * Math.PI / 180;
    const inclination = Number(result.parent.omm.INCLINATION) * Math.PI / 180;
    const node = Number(result.parent.omm.RA_OF_ASC_NODE) * Math.PI / 180;
    const radius = Math.cbrt(398600.4418 / (motion * motion)) / 6378.137;
    const x = Math.cos(phase) * radius, y = Math.sin(phase) * Math.sin(inclination) * radius, z = -Math.sin(phase) * Math.cos(inclination) * radius;
    return { geometry, radius, phase, burstPosition: [x * Math.cos(node) + z * Math.sin(node), y, -x * Math.sin(node) + z * Math.cos(node)] as [number, number, number] };
  }, [result]);
  useEffect(() => () => data.geometry.dispose(), [data.geometry]);
  const uniforms = useMemo(() => ({ uYear: { value: 0 }, uRadius: { value: data.radius }, uInclination: { value: Number(result.parent.omm.INCLINATION) * Math.PI / 180 }, uNode: { value: Number(result.parent.omm.RA_OF_ASC_NODE) * Math.PI / 180 }, uPhase: { value: data.phase }, uPixelRatio: { value: Math.min(gl.getPixelRatio(), 1.5) } }), [result, data.radius, data.phase, gl]);
  useFrame(() => {
    if (material.current) material.current.uniforms.uYear.value = Math.max(0.001, year);
    if (burst.current) {
      const age = (performance.now() - started.current) / 1000;
      burst.current.visible = age < 2.5 && !reduced;
      burst.current.scale.setScalar(0.02 + age * 0.15);
      (burst.current.material as ShaderMaterial).opacity = Math.max(0, 1 - age / 2.5);
    }
  });
  return <>
    <points geometry={data.geometry} frustumCulled={false} raycast={() => null}><shaderMaterial ref={material} vertexShader={vertex} fragmentShader={fragment} uniforms={uniforms} transparent blending={AdditiveBlending} depthWrite={false} /></points>
    <Billboard position={data.burstPosition}><mesh ref={burst}><ringGeometry args={[0.8, 1, 64]} /><meshBasicMaterial color="#ffe5b9" transparent opacity={0.8} depthWrite={false} blending={AdditiveBlending} /></mesh></Billboard>
    {result.secondaryCollisions.filter(event => year >= event.year).map((event, i) => <SecondaryCloud key={i} event={event} year={year} seed={result.seed + i + 1} />)}
    {result.secondaryCollisions.filter(event => year >= event.year).map((event, i) => {
      const latitude = event.latDeg * Math.PI / 180, longitude = event.lonDeg * Math.PI / 180 + gstime(new Date(useSimStore.getState().timeMs));
      const radius = 1 + event.altKm / 6378.137;
      return <Billboard key={i} position={[radius * Math.cos(latitude) * Math.cos(longitude), radius * Math.sin(latitude), -radius * Math.cos(latitude) * Math.sin(longitude)]}><mesh scale={1 + Math.max(0, 1 - Math.abs(year - event.year))}><ringGeometry args={[0.023, 0.027, 40]} /><meshBasicMaterial color="#ffbf71" transparent opacity={Math.max(0.25, 1 - Math.abs(year - event.year))} depthTest={false} /></mesh></Billboard>;
    })}
  </>;
}

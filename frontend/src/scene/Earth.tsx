import { Suspense, useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import { useTexture } from '@react-three/drei';
import { AdditiveBlending, Color, FrontSide, Group, ShaderMaterial, Vector3 } from 'three';
import { gstime } from 'satellite.js';
import { useSimStore } from '../sim/store';
import earthVertex from './earth.vert.glsl?raw';
import earthFragment from './earth.frag.glsl?raw';
import atmosphereFragment from './atmosphere.frag.glsl?raw';

/** Approximate geocentric solar direction in the same TEME-like scene frame as SGP4. */
export function solarDirection(timeMs: number, target = new Vector3()) {
  const days = timeMs / 86_400_000 - 10_957.5;
  const mean = ((357.528 + 0.9856003 * days) * Math.PI) / 180;
  const longitude = ((280.46 + 0.9856474 * days + 1.915 * Math.sin(mean) + 0.02 * Math.sin(2 * mean)) * Math.PI) / 180;
  const obliquity = (23.439 * Math.PI) / 180;
  return target.set(Math.cos(longitude), Math.sin(obliquity) * Math.sin(longitude), -Math.cos(obliquity) * Math.sin(longitude)).normalize();
}

function TexturedEarth({ quality }: { quality: 'high' | 'low' }) {
  const [day, night, clouds, water] = useTexture(['/textures/earth-day.webp', '/textures/earth-night.webp', '/textures/earth-clouds.webp', '/textures/earth-water.png']);
  const earth = useRef<Group>(null);
  const cloud = useRef<Group>(null);
  const sun = useMemo(() => solarDirection(useSimStore.getState().timeMs), []);
  const earthUniforms = useMemo(() => ({ uDay: { value: day }, uNight: { value: night }, uWater: { value: water }, uClouds: { value: clouds }, uSun: { value: sun } }), [day, night, water, clouds, sun]);
  const atmosphereUniforms = useMemo(() => ({ uSun: { value: sun } }), [sun]);
  const date = useMemo(() => new Date(), []);
  useFrame(() => {
    const timeMs = useSimStore.getState().timeMs;
    solarDirection(timeMs, sun);
    date.setTime(timeMs);
    const sidereal = gstime(date);
    if (earth.current) earth.current.rotation.y = sidereal;
    if (cloud.current) cloud.current.rotation.y = sidereal + (timeMs / 86_400_000) * 0.015;
  });
  return <>
    <group ref={earth}>
      <mesh><sphereGeometry args={[1, quality === 'high' ? 96 : 48, quality === 'high' ? 64 : 32]} />
        <shaderMaterial vertexShader={earthVertex} fragmentShader={earthFragment} uniforms={earthUniforms} />
      </mesh>
    </group>
    {quality === 'high' && <group ref={cloud}><mesh><sphereGeometry args={[1.004, 64, 48]} />
      <meshStandardMaterial map={clouds} transparent opacity={0.30} depthWrite={false} color="#dae9f2" roughness={1} />
    </mesh></group>}
    <mesh><sphereGeometry args={[1.021, 64, 48]} />
      <shaderMaterial vertexShader={earthVertex} fragmentShader={atmosphereFragment} uniforms={atmosphereUniforms} transparent blending={AdditiveBlending} depthWrite={false} side={FrontSide} />
    </mesh>
  </>;
}

export function EarthFallback() {
  return <mesh><sphereGeometry args={[1, 64, 48]} /><meshStandardMaterial color={new Color('#12394c')} roughness={0.86} metalness={0.15} /></mesh>;
}

export default function Earth({ quality }: { quality: 'high' | 'low' }) {
  return <Suspense fallback={<EarthFallback />}><TexturedEarth quality={quality} /></Suspense>;
}

export type EarthShader = ShaderMaterial;

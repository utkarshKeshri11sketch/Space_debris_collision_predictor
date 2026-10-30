import { useEffect, useMemo } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import { BufferAttribute, BufferGeometry } from 'three';
import ShootingStars from './ShootingStars';

const vertex = `
  attribute vec3 color;
  attribute float aPhase;
  attribute float aBrightness;
  uniform float uTime;
  uniform float uMotion;
  uniform float uPixelRatio;
  varying vec3 vColor;
  varying float vBrightness;
  void main() {
    // Decorative scintillation only; catalog positions remain physically propagated.
    float shimmer = 1.0 + 0.12 * sin(uTime * (0.35 + fract(aPhase) * 0.3) + aPhase) * uMotion;
    vColor = color;
    vBrightness = aBrightness * shimmer;
    gl_PointSize = (1.2 + min(aBrightness, 3.0) * 0.65) * uPixelRatio;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;
const fragment = `
  varying vec3 vColor;
  varying float vBrightness;
  void main() {
    float radius = length(gl_PointCoord - 0.5) * 2.0;
    if (radius > 1.0) discard;
    float core = exp(-radius * radius * 5.0);
    gl_FragColor = vec4(vColor * vBrightness, core * 0.86);
  }
`;

export default function LivingSky({ quality }: { quality: 'high' | 'low' }) {
  const { gl } = useThree();
  const geometry = useMemo(() => {
    const count = quality === 'high' ? 12000 : 4000;
    const positions = new Float32Array(count * 3);
    const colors = new Float32Array(count * 3);
    const phases = new Float32Array(count);
    const brightness = new Float32Array(count);
    let seed = 137;
    const random = () => { seed = Math.imul(seed, 1664525) + 1013904223 | 0; return (seed >>> 0) / 4294967296; };
    for (let i = 0; i < count; i++) {
      const y = random() * 2 - 1, angle = random() * Math.PI * 2;
      const horizontal = Math.sqrt(1 - y * y);
      positions.set([Math.cos(angle) * horizontal * 90, y * 90, Math.sin(angle) * horizontal * 90], i * 3);
      const warm = random() > 0.84;
      colors.set(warm ? [1, 0.82, 0.65] : [0.73, 0.85, 1], i * 3);
      phases[i] = random() * Math.PI * 20;
      // Sparse HDR stars glow; the majority stays subdued behind the operational view.
      brightness[i] = random() > 0.986 ? 3.2 : 0.15 + Math.pow(random(), 4) * 0.65;
    }
    const result = new BufferGeometry();
    result.setAttribute('position', new BufferAttribute(positions, 3));
    result.setAttribute('color', new BufferAttribute(colors, 3));
    result.setAttribute('aPhase', new BufferAttribute(phases, 1));
    result.setAttribute('aBrightness', new BufferAttribute(brightness, 1));
    return result;
  }, [quality]);
  const uniforms = useMemo(() => ({ uTime: { value: 0 }, uMotion: { value: 1 }, uPixelRatio: { value: gl.getPixelRatio() } }), [gl]);
  useEffect(() => {
    const preference = window.matchMedia('(prefers-reduced-motion: reduce)');
    const update = () => { uniforms.uMotion.value = preference.matches ? 0 : 1; };
    update();
    preference.addEventListener('change', update);
    return () => preference.removeEventListener('change', update);
  }, [uniforms]);
  useEffect(() => () => geometry.dispose(), [geometry]);
  useFrame(({ clock }) => {
    uniforms.uTime.value = clock.elapsedTime;
    uniforms.uPixelRatio.value = Math.min(gl.getPixelRatio(), 1.75);
  });
  return <><points geometry={geometry} raycast={() => null}>
    <shaderMaterial vertexShader={vertex} fragmentShader={fragment} uniforms={uniforms} transparent depthWrite={false} toneMapped={false} />
  </points>{quality === 'high' && <ShootingStars />}</>;
}

import { useEffect, useMemo, useRef } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import { NormalBlending, BufferAttribute, BufferGeometry, ShaderMaterial, Vector3 } from 'three';
import type { CatalogObject } from '../api/types';
import { createPropagationClient } from '../sim/propagation';
import { useSimStore } from '../sim/store';
import vertex from './objects.vert.glsl?raw';
import fragment from './objects.frag.glsl?raw';

export type LayerVisibility = { payload: boolean; debris: boolean; rocket: boolean };
export type OrbitRegime = 'ALL' | 'LEO' | 'MEO' | 'GEO';
export type PositionBuffers = { current: Float32Array; previous: Float32Array; updatedAt: number };
const regimeCode = { ALL: 0, LEO: 1, MEO: 2, GEO: 3 };

export function initialPositions(catalog: CatalogObject[]) {
  const positions = new Float32Array(catalog.length * 3);
  catalog.forEach((object, i) => {
    const inclination = (Number(object.omm.INCLINATION) * Math.PI) / 180;
    const node = (Number(object.omm.RA_OF_ASC_NODE) * Math.PI) / 180;
    const phase = (Number(object.omm.MEAN_ANOMALY) * Math.PI) / 180;
    const motion = (Number(object.omm.MEAN_MOTION) * Math.PI * 2) / 86400;
    const radius = Math.cbrt(398600.4418 / (motion * motion)) / 6378.137;
    const x = radius * Math.cos(phase);
    const y = radius * Math.sin(phase) * Math.cos(inclination);
    positions[i * 3] = x * Math.cos(node) - y * Math.sin(node);
    positions[i * 3 + 1] = radius * Math.sin(phase) * Math.sin(inclination);
    positions[i * 3 + 2] = -(x * Math.sin(node) + y * Math.cos(node));
  });
  return positions;
}

export default function ObjectCloud({ catalog, layers, regime, buffers, onWorkerError, selectedIndex = -1, hoveredIndex = -1 }: {
  catalog: CatalogObject[]; layers: LayerVisibility; regime: OrbitRegime;
  buffers: React.MutableRefObject<PositionBuffers>; onWorkerError: (message: string) => void;
  selectedIndex?: number; hoveredIndex?: number;
}) {
  const { gl } = useThree();
  const material = useRef<ShaderMaterial>(null);
  const geometry = useMemo(() => {
    const result = new BufferGeometry();
    const initial = initialPositions(catalog);
    const types = new Float32Array(catalog.length);
    const regimes = new Float32Array(catalog.length);
    const seeds = new Float32Array(catalog.length);
    catalog.forEach((object, i) => {
      types[i] = object.type === 'PAYLOAD' ? 0 : object.type === 'DEBRIS' ? 1 : 2;
      const radius = Math.hypot(initial[i * 3], initial[i * 3 + 1], initial[i * 3 + 2]);
      regimes[i] = radius < 1.35 ? 1 : radius > 6 ? 3 : 2;
      seeds[i] = i;
    });
    result.setAttribute('position', new BufferAttribute(initial, 3));
    result.setAttribute('aPrevious', new BufferAttribute(initial.slice(), 3));
    result.setAttribute('aType', new BufferAttribute(types, 1));
    result.setAttribute('aRegime', new BufferAttribute(regimes, 1));
    result.setAttribute('aSeed', new BufferAttribute(seeds, 1));
    buffers.current = { current: initial, previous: initial, updatedAt: performance.now() };
    return result;
  }, [catalog, buffers]);
  const uniforms = useMemo(() => ({ uBlend: { value: 1 }, uPixelRatio: { value: Math.min(gl.getPixelRatio(), 1.75) }, uTime: { value: 0 }, uMotion: { value: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 1 }, uLayers: { value: new Vector3(1, 1, 1) }, uRegime: { value: 0 }, uSelectedIndex: { value: -1 }, uHoveredIndex: { value: -1 } }), [gl]);
  useEffect(() => {
    const client = createPropagationClient();
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    const update = async () => {
      if (disposed) return;
      try {
        if (!document.hidden) {
          const positions = await client.propagate(useSimStore.getState().timeMs);
          if (disposed) return;
          const previous = buffers.current.current;
          geometry.setAttribute('aPrevious', new BufferAttribute(previous, 3));
          geometry.setAttribute('position', new BufferAttribute(positions, 3));
          buffers.current = { current: positions, previous, updatedAt: performance.now() };
        }
      } catch (error) {
        if (!disposed) onWorkerError(error instanceof Error ? error.message : 'Orbit propagation unavailable.');
      }
      if (!disposed) timer = setTimeout(update, 200);
    };
    client.init(catalog).then(() => { if (!disposed) void update(); }).catch((error: unknown) => { if (!disposed) onWorkerError(error instanceof Error ? error.message : 'Orbit propagation unavailable.'); });
    return () => { disposed = true; clearTimeout(timer); client.dispose(); };
  }, [catalog, geometry, buffers, onWorkerError]);
  useEffect(() => () => geometry.dispose(), [geometry]);
  useFrame(({ clock }) => {
    if (!material.current) return;
    uniforms.uBlend.value = Math.min((performance.now() - buffers.current.updatedAt) / 200, 1);
    uniforms.uTime.value = clock.elapsedTime;
    uniforms.uLayers.value.set(Number(layers.payload), Number(layers.debris), Number(layers.rocket));
    uniforms.uRegime.value = regimeCode[regime];
    uniforms.uSelectedIndex.value = selectedIndex;
    uniforms.uHoveredIndex.value = hoveredIndex;
  });
  return <points geometry={geometry} frustumCulled={false} raycast={() => null}>
    <shaderMaterial ref={material} vertexShader={vertex} fragmentShader={fragment} uniforms={uniforms} transparent depthWrite={false} blending={NormalBlending} />
  </points>;
}

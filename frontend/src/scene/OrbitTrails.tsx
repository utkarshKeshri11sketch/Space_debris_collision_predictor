import { useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import { Billboard, Html, Line } from '@react-three/drei';
import { Group, Mesh, Vector3 } from 'three';
import { json2satrec, propagate, type OMMJsonObject } from 'satellite.js';
import type { CatalogObject, Conjunction } from '../api/types';
import { useSimStore } from '../sim/store';
import type { PositionBuffers } from './ObjectCloud';

const EARTH_KM = 6378.137;
export function objectPositionAt(object: CatalogObject, timeMs: number) {
  const record = json2satrec(object.omm as unknown as OMMJsonObject);
  const result = propagate(record, new Date(timeMs));
  return result
    ? new Vector3(
        result.position.x / EARTH_KM,
        result.position.z / EARTH_KM,
        -result.position.y / EARTH_KM,
      )
    : null;
}
export function orbitPoints(object: CatalogObject, timeMs: number) {
  const record = json2satrec(object.omm as unknown as OMMJsonObject);
  const period = 86_400_000 / Number(object.omm.MEAN_MOTION);
  const points: Vector3[] = [];
  for (let i = 0; i <= 180; i++) {
    const result = propagate(record, new Date(timeMs + (i / 180) * period));
    if (result)
      points.push(
        new Vector3(
          result.position.x / EARTH_KM,
          result.position.z / EARTH_KM,
          -result.position.y / EARTH_KM,
        ),
      );
  }
  return points;
}

function SatelliteModel() {
  return (
    <group scale={0.017} rotation={[0.2, 0, 0.45]}>
      <mesh>
        <boxGeometry args={[0.7, 0.8, 0.7]} />
        <meshStandardMaterial color="#ff5d66" metalness={0.48} roughness={0.4} />
      </mesh>
      {[-1, 1].map((side) => (
        <group key={side} position={[side * 1.3, 0, 0]}>
          <mesh>
            <boxGeometry args={[1.75, 0.035, 0.85]} />
            <meshStandardMaterial color="#5b1e2a" metalness={0.65} roughness={0.23} />
          </mesh>
          {[0, 1, 2, 3, 4].map((cell) => (
            <mesh key={cell} position={[-0.66 + cell * 0.33, 0.025, 0]}>
              <boxGeometry args={[0.012, 0.012, 0.85]} />
              <meshBasicMaterial color="#db8692" />
            </mesh>
          ))}
        </group>
      ))}
      <mesh position={[0, 0.55, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <coneGeometry args={[0.4, 0.2, 24, 1, true]} />
        <meshStandardMaterial color="#e7edf4" side={2} />
      </mesh>
    </group>
  );
}

export function SelectedObject({
  object,
  index,
  buffers,
  closeUp,
}: {
  object: CatalogObject;
  index: number;
  buffers: React.MutableRefObject<PositionBuffers>;
  closeUp: boolean;
}) {
  const group = useRef<Group>(null);
  const ring = useRef<Mesh>(null);
  const reduced = useMemo(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches, []);
  const points = useMemo(() => orbitPoints(object, useSimStore.getState().timeMs), [object]);
  useFrame(({ clock }) => {
    const positions = buffers.current.current;
    if (group.current && positions.length > index * 3 + 2)
      group.current.position.set(
        positions[index * 3],
        positions[index * 3 + 1],
        positions[index * 3 + 2],
      );
    if (ring.current && !reduced) ring.current.rotation.z = clock.elapsedTime * 0.12;
  });
  return (
    <>
      {points.length > 1 && (
        <Line
          points={points}
          color={
            object.type === 'DEBRIS' ? '#ff8a3d' : object.type === 'PAYLOAD' ? '#ff5d66' : '#b7c0d1'
          }
          transparent
          opacity={0.68}
          lineWidth={1.2}
        />
      )}
      <group ref={group}>
        <Billboard>
          <mesh ref={ring}>
            <ringGeometry args={[0.022, 0.025, 40]} />
            <meshBasicMaterial
              color={
                object.type === 'PAYLOAD'
                  ? '#ff5d66'
                  : object.type === 'DEBRIS'
                    ? '#ff8a3d'
                    : '#b7c0d1'
              }
              transparent
              opacity={0.95}
              depthTest={false}
            />
          </mesh>
          <mesh>
            <circleGeometry args={[0.007, 20]} />
            <meshBasicMaterial
              color={
                object.type === 'PAYLOAD'
                  ? '#ff5d66'
                  : object.type === 'DEBRIS'
                    ? '#ff8a3d'
                    : '#b7c0d1'
              }
              depthTest={false}
            />
          </mesh>
        </Billboard>
        {closeUp && object.type === 'PAYLOAD' && <SatelliteModel />}
        <Html
          position={[0.07, 0.06, 0]}
          style={{ pointerEvents: 'none', whiteSpace: 'nowrap' }}
          occlude
        >
          <div className="scene-object-label">
            <i />
            {object.name}
            <small>NORAD {object.noradId}</small>
          </div>
        </Html>
      </group>
    </>
  );
}

export function Encounter({
  conjunction,
  primary,
  replayProgress = 0.5,
  previewBurn = false,
}: {
  conjunction: Conjunction;
  primary: CatalogObject;
  replayProgress?: number;
  previewBurn?: boolean;
}) {
  const pulse = useRef<Mesh>(null);
  const reduced = useMemo(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches, []);
  const geometry = useMemo(() => {
    const anchor =
      objectPositionAt(primary, new Date(conjunction.tca).getTime()) ??
      new Vector3(0.6, 0.6, 0.65).normalize().multiplyScalar(1.07);
    const radial = anchor.clone().normalize();
    const tangent = new Vector3().crossVectors(radial, new Vector3(0.2, 1, 0.4)).normalize();
    const alternate = tangent.clone().applyAxisAngle(radial, 1.4);
    const primaryPath: Vector3[] = [],
      secondaryPath: Vector3[] = [],
      afterPath: Vector3[] = [];
    for (let i = 0; i <= 140; i++) {
      const angle = ((i / 140) * 2 - 1) * 1.55;
      primaryPath.push(
        radial
          .clone()
          .multiplyScalar(Math.cos(angle) * anchor.length())
          .addScaledVector(tangent, Math.sin(angle) * anchor.length()),
      );
      secondaryPath.push(
        radial
          .clone()
          .multiplyScalar(Math.cos(angle) * (anchor.length() + 0.007))
          .addScaledVector(alternate, Math.sin(angle) * anchor.length()),
      );
      afterPath.push(
        radial
          .clone()
          .multiplyScalar(Math.cos(angle) * (anchor.length() + 0.055))
          .addScaledVector(tangent, Math.sin(angle) * anchor.length()),
      );
    }
    return { anchor, primaryPath, secondaryPath, afterPath };
  }, [primary, conjunction.tca]);
  useFrame(({ clock }) => {
    if (pulse.current && !reduced)
      pulse.current.scale.setScalar(1 + Math.sin(clock.elapsedTime * 2.3) * 0.12);
  });
  const index = Math.min(140, Math.max(0, Math.round(replayProgress * 140)));
  return (
    <group>
      <Line
        points={geometry.primaryPath}
        color="#ff5d66"
        lineWidth={1.7}
        transparent
        opacity={0.88}
      />
      <Line
        points={geometry.secondaryPath}
        color={conjunction.secondary.type === 'PAYLOAD' ? '#ff5d66' : '#ff8a3d'}
        lineWidth={1.6}
        transparent
        opacity={0.82}
        dashed
        dashSize={0.035}
        gapSize={0.022}
      />
      {previewBurn && (
        <Line
          points={geometry.afterPath}
          color="#3ddc97"
          lineWidth={1.4}
          dashed
          dashSize={0.04}
          gapSize={0.025}
          transparent
          opacity={0.85}
        />
      )}
      <group position={geometry.anchor}>
        <Billboard>
          <mesh ref={pulse}>
            <ringGeometry args={[0.048, 0.052, 64]} />
            <meshBasicMaterial
              color={conjunction.risk === 'critical' ? '#ff5d5d' : '#f2c14e'}
              transparent
              opacity={0.85}
              depthTest={false}
            />
          </mesh>
        </Billboard>
        <Html position={[0.07, 0.12, 0]} occlude style={{ pointerEvents: 'none' }}>
          <div className="scene-encounter-label">
            <span>TIME OF CLOSEST APPROACH</span>
            <strong>{conjunction.missDistanceM.toLocaleString()} m</strong>
            <small>Encounter geometry magnified</small>
          </div>
        </Html>
      </group>
      <mesh position={geometry.primaryPath[index]}>
        <sphereGeometry args={[0.014, 12, 12]} />
        <meshBasicMaterial color="#ff5d66" />
      </mesh>
      <mesh position={geometry.secondaryPath[140 - index]}>
        <sphereGeometry args={[0.011, 12, 12]} />
        <meshBasicMaterial
          color={conjunction.secondary.type === 'PAYLOAD' ? '#ff5d66' : '#ff8a3d'}
        />
      </mesh>
    </group>
  );
}

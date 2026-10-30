import { useEffect, useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import { AdditiveBlending, Group, PlaneGeometry, ShaderMaterial } from 'three';
import { useReducedMotion } from '../../ui/useReducedMotion';

/** Decorative sky streaks: three persistent meshes share one geometry/material. */
export default function ShootingStars() {
  const group = useRef<Group>(null);
  const reduced = useReducedMotion();
  const geometry = useMemo(() => new PlaneGeometry(4, 0.045), []);
  const material = useMemo(() => new ShaderMaterial({
    transparent: true, depthWrite: false, toneMapped: false, blending: AdditiveBlending,
    vertexShader: `varying vec2 vUv; void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
    fragmentShader: `varying vec2 vUv; void main() {
      float tail = pow(vUv.x, 2.0) * (1.0 - smoothstep(0.9, 1.0, vUv.x));
      float edge = 1.0 - abs(vUv.y * 2.0 - 1.0);
      gl_FragColor = vec4(vec3(0.8, 1.3, 1.8), tail * edge * 0.65);
    }`,
  }), []);
  useEffect(() => () => { geometry.dispose(); material.dispose(); }, [geometry, material]);
  useFrame(({ camera, clock }) => {
    if (!group.current || reduced) return;
    group.current.position.copy(camera.position);
    group.current.quaternion.copy(camera.quaternion);
    group.current.children.forEach((mesh, index) => {
      const phase = (clock.elapsedTime + index * 8) % 24;
      const progress = phase / 1.6;
      mesh.visible = progress <= 1;
      if (!mesh.visible) return;
      mesh.position.set(-20 + progress * 34, 12 - index * 3 - progress * 7, -45);
      mesh.rotation.z = -0.2;
      mesh.scale.setScalar(Math.sin(progress * Math.PI));
    });
  });
  if (reduced) return null;
  return <group ref={group}>
    {[0, 1, 2].map(index => <mesh key={index} geometry={geometry} material={material} visible={false} raycast={() => null} />)}
  </group>;
}

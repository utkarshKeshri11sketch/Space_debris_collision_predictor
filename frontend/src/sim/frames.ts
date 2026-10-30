export const EARTH_RADIUS_KM = 6378.137;
export interface Cartesian { x: number; y: number; z: number }
/** TEME uses z north. Three uses y north; this right-handed mapping preserves distance. */
export function temeToScene(position: Cartesian): [number, number, number] {
  return [position.x / EARTH_RADIUS_KM, position.z / EARTH_RADIUS_KM, -position.y / EARTH_RADIUS_KM];
}
export function writeTemeToScene(position: Cartesian, target: Float32Array, offset: number): void {
  target[offset] = position.x / EARTH_RADIUS_KM;
  target[offset + 1] = position.z / EARTH_RADIUS_KM;
  target[offset + 2] = -position.y / EARTH_RADIUS_KM;
}

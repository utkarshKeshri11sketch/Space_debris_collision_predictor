import { describe, expect, it } from 'vitest';
import { EARTH_RADIUS_KM, temeToScene, writeTemeToScene } from './frames';
describe('TEME to Three.js scene mapping', () => {
  it('maps north to positive scene Y with Earth radius one', () => {
    expect(temeToScene({ x: 0, y: 0, z: EARTH_RADIUS_KM })).toEqual([0, 1, -0]);
    expect(temeToScene({ x: EARTH_RADIUS_KM, y: 0, z: 0 })).toEqual([1, 0, -0]);
  });
  it('preserves scaled distance and writes at the requested buffer offset', () => {
    const position = { x: 1000, y: -5000, z: 2000 };
    const result = temeToScene(position);
    expect(Math.hypot(...result)).toBeCloseTo(Math.hypot(...Object.values(position)) / EARTH_RADIUS_KM);
    const buffer = new Float32Array(9).fill(-99);
    writeTemeToScene(position, buffer, 3);
    expect(buffer[0]).toBe(-99);
    expect(buffer[3]).toBeCloseTo(result[0]);
    expect(buffer[4]).toBeCloseTo(result[1]);
    expect(buffer[5]).toBeCloseTo(result[2]);
    expect(buffer[6]).toBe(-99);
  });
});

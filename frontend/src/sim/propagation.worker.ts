import { expose, transfer } from 'comlink';
import { propagate, type SatRec } from 'satellite.js';
import type { CatalogObject } from '../api/types';
import { recordFromOmm } from './omm';
import { writeTemeToScene } from './frames';
let records: (SatRec | null)[] = [];
let ids = new Map<number, number>();
let catalog: CatalogObject[] = [];
const workerApi = {
  init(objects: CatalogObject[]): number {
    catalog = objects;
    ids = new Map(objects.map((object, index) => [object.noradId, index]));
    records = objects.map((object) => {
      try { return recordFromOmm(object.omm); } catch { return null; }
    });
    return records.filter(Boolean).length;
  },
  propagate(timeMs: number): Float32Array {
    const positions = new Float32Array(records.length * 3);
    const date = new Date(timeMs);
    for (let index = 0; index < records.length; index++) {
      const record = records[index];
      if (!record) continue;
      const result = propagate(record, date);
      if (result) writeTemeToScene(result.position, positions, index * 3);
    }
    return transfer(positions, [positions.buffer]);
  },
  orbit(noradId: number, timeMs: number, samples = 180): Float32Array {
    const index = ids.get(noradId);
    const count = Math.max(12, Math.min(720, Math.round(samples)));
    const positions = new Float32Array((count + 1) * 3);
    if (index === undefined || !records[index]) return positions;
    const record = records[index];
    const periodMs = 86400000 / Number(catalog[index].omm.MEAN_MOTION);
    for (let i = 0; i <= count; i++) {
      const result = propagate(record, new Date(timeMs + (i / count) * periodMs));
      if (result) writeTemeToScene(result.position, positions, i * 3);
    }
    return transfer(positions, [positions.buffer]);
  },
};
export type PropagationWorkerApi = typeof workerApi;
expose(workerApi);

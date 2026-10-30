import { wrap, releaseProxy } from 'comlink';
import type { PropagationWorkerApi } from './propagation.worker';
export function createPropagationClient() {
  const worker = new Worker(new URL('./propagation.worker.ts', import.meta.url), { type: 'module' });
  const remote = wrap<PropagationWorkerApi>(worker);
  return {
    init: remote.init,
    propagate: remote.propagate,
    orbit: remote.orbit,
    dispose() { remote[releaseProxy](); worker.terminate(); },
  };
}
export type PropagationClient = ReturnType<typeof createPropagationClient>;

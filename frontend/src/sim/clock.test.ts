import { beforeEach, describe, expect, it } from 'vitest';
import { SIM_HORIZON_MS, useSimStore } from './clock';
describe('shared simulation clock', () => {
  beforeEach(() => useSimStore.getState().reset());
  it('applies speed once and respects pause', () => {
    const state = useSimStore.getState();
    state.setSpeed(600);
    state.tick(100);
    expect(useSimStore.getState().timeMs).toBe(state.epochMs + 60000);
    state.togglePlaying();
    state.tick(1000);
    expect(useSimStore.getState().timeMs).toBe(state.epochMs + 60000);
  });
  it('clamps scrubbing and playback to the screening horizon', () => {
    const state = useSimStore.getState();
    state.setTime(state.epochMs - 10000);
    expect(useSimStore.getState().timeMs).toBe(state.epochMs);
    state.setTime(state.epochMs + SIM_HORIZON_MS - 10);
    state.tick(100);
    expect(useSimStore.getState().timeMs).toBe(state.epochMs + SIM_HORIZON_MS);
    expect(useSimStore.getState().playing).toBe(false);
  });
  it('ignores invalid speed and elapsed time', () => {
    const state = useSimStore.getState();
    state.setSpeed(-1);
    state.tick(NaN);
    expect(useSimStore.getState().speed).toBe(1);
    expect(useSimStore.getState().timeMs).toBe(state.epochMs);
  });
});

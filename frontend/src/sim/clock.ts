import { useEffect } from 'react';
import { create } from 'zustand';
export const SIM_SPEEDS = [1, 60, 600, 3600] as const;
export const SIM_HORIZON_MS = 7 * 24 * 60 * 60 * 1000;
interface SimState {
  epochMs: number;
  timeMs: number;
  playing: boolean;
  speed: number;
  setTime: (timeMs: number) => void;
  setSpeed: (speed: number) => void;
  togglePlaying: () => void;
  tick: (elapsedMs: number) => void;
  reset: () => void;
}
const epochMs = Date.now();
export const useSimStore = create<SimState>((set, get) => ({
  epochMs, timeMs: epochMs, playing: true, speed: 1,
  setTime: (timeMs) => set({ timeMs: Math.max(get().epochMs, Math.min(get().epochMs + SIM_HORIZON_MS, timeMs)) }),
  setSpeed: (speed) => { if (SIM_SPEEDS.some((allowed) => allowed === speed)) set({ speed }); },
  togglePlaying: () => set((state) => ({ playing: !state.playing })),
  tick: (elapsedMs) => {
    const state = get();
    if (!state.playing || !Number.isFinite(elapsedMs) || elapsedMs <= 0) return;
    const next = Math.min(state.epochMs + SIM_HORIZON_MS, state.timeMs + elapsedMs * state.speed);
    set({ timeMs: next, playing: next < state.epochMs + SIM_HORIZON_MS });
  },
  reset: () => set({ timeMs: get().epochMs, playing: true, speed: 1 }),
}));
/** One UI ticker. Hidden tabs resume without jumping by their entire suspended duration. */
export function SimClockTicker() {
  useEffect(() => {
    let last = performance.now();
    const timer = window.setInterval(() => {
      const now = performance.now();
      if (!document.hidden) useSimStore.getState().tick(Math.min(now - last, 500));
      last = now;
    }, 100);
    return () => window.clearInterval(timer);
  }, []);
  return null;
}

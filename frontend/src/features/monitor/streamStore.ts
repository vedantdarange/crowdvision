import { create } from 'zustand';
import type { FrameResult } from '@contract/types';
import type { LatencyStats, StreamerState } from './useFrameStreamer';

export type FrameStreamError = NonNullable<FrameResult['error']>;

export interface MonitorStreamSnapshot {
  activeSourceId: number | null;
  state: StreamerState;
  fps: number;
  latencyMs: LatencyStats;
  drops: number;
  lastResult: FrameResult | null;
  lastResultAt: number | null;
  lastError: FrameStreamError | null;
  inUseSourceId: number | null;
}

const INITIAL_SNAPSHOT: MonitorStreamSnapshot = {
  activeSourceId: null,
  state: 'idle',
  fps: 0,
  latencyMs: { p50: 0, p95: 0 },
  drops: 0,
  lastResult: null,
  lastResultAt: null,
  lastError: null,
  inUseSourceId: null,
};

export const useMonitorStore = create<MonitorStreamSnapshot>(
  () => INITIAL_SNAPSHOT,
);

let activeOwner: { id: symbol; stop: () => void } | null = null;

/**
 * Enforces strictly ONE active stream per browser tab.
 * Claiming ownership automatically stops any previously active streamer.
 */
export function claimActiveStream(id: symbol, stop: () => void) {
  if (activeOwner && activeOwner.id !== id) {
    activeOwner.stop();
  }
  activeOwner = { id, stop };
}

export function releaseActiveStream(id: symbol) {
  if (activeOwner?.id === id) {
    activeOwner = null;
  }
}

export function isActiveStreamOwner(id: symbol): boolean {
  return activeOwner?.id === id;
}

export function clearStreamErrors() {
  useMonitorStore.setState({ lastError: null, inUseSourceId: null });
}

export function resetStreamSnapshot() {
  useMonitorStore.setState(INITIAL_SNAPSHOT);
}

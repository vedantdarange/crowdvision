import { useEffect, type ReactNode } from 'react';
import { create } from 'zustand';
import { toast } from 'sonner';
import { socket } from '@/lib/socket';
import { API_BASE } from '@/lib/constants';
import { ApiRequestError } from '@/lib/request';
import { queryClient } from '@/lib/queryClient';
import { useSession } from '@/features/auth';
import { refreshSession } from '@/lib/apiClient';
import { useConfig } from '@/features/zones/api';
import { updateZone, updateAdvisory } from './cache';
export const useConnection = create<{
  status: 'connected' | 'reconnecting' | 'offline';
}>(() => ({
  status:
    typeof navigator !== 'undefined' && navigator.onLine === false
      ? 'offline'
      : 'reconnecting',
}));
import {
  updateAlert,
  updatePoliceZone,
  updateSource,
  useSeries,
} from '@/features/police/data';
import { updateReportInCache } from '@/features/reports/api';

const SILENCE_PROBE_AFTER_MS = 6_000;
const WATCHDOG_INTERVAL_MS = 4_000;
const HEALTH_TIMEOUT_MS = 3_000;

let started = false;
let needsResync = false;
let socketAlive = false;
let resyncGeneration = 0;
let lastServerActivityAt = Date.now();
let probingHealth = false;

function isBrowserOffline(): boolean {
  return typeof navigator !== 'undefined' && navigator.onLine === false;
}

function isConnectivityError(error: unknown): boolean {
  if (!error) return false;
  if (error instanceof ApiRequestError) {
    return error.status >= 502;
  }
  if (error instanceof DOMException && error.name === 'AbortError') {
    return false;
  }
  return error instanceof Error;
}

function reconnectSocket() {
  socket.disconnect();
  socket.auth = { token: useSession.getState().tokens?.access_token };
  socket.connect();
}

function markConnectionLost(
  mode: 'offline' | 'reconnecting',
  reconnect = false,
) {
  needsResync = true;
  socketAlive = false;
  resyncGeneration += 1;
  useConnection.setState({ status: mode });
  if (mode === 'offline') {
    socket.disconnect();
  } else if (reconnect) {
    reconnectSocket();
  }
}

async function finishResyncAndConnect(gen: number) {
  try {
    void queryClient.invalidateQueries({ refetchType: 'none' });
    await queryClient.refetchQueries({ type: 'active' });
  } catch {
    // Failure state is inspected on the active queries below.
  }
  if (gen !== resyncGeneration) return;
  if (isBrowserOffline()) {
    useConnection.setState({ status: 'offline' });
    return;
  }
  const hasNetworkFailure = queryClient
    .getQueryCache()
    .findAll({ type: 'active' })
    .some(
      (q) => q.state.status === 'error' && isConnectivityError(q.state.error),
    );
  if (hasNetworkFailure || !socketAlive) {
    useConnection.setState({ status: 'reconnecting' });
    return;
  }
  needsResync = false;
  lastServerActivityAt = Date.now();
  useConnection.setState({ status: 'connected' });
}

async function checkBackendHealth() {
  if (probingHealth || typeof fetch !== 'function') return;
  if (isBrowserOffline()) {
    if (useConnection.getState().status !== 'offline') {
      markConnectionLost('offline');
    }
    return;
  }

  probingHealth = true;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), HEALTH_TIMEOUT_MS);
  try {
    const response = await fetch(`${API_BASE}/health`, {
      cache: 'no-store',
      signal: controller.signal,
    });
    if (!response.ok && response.status >= 500) {
      throw new Error('Backend unavailable');
    }
    lastServerActivityAt = Date.now();
    if (
      useConnection.getState().status === 'reconnecting' &&
      !socketAlive &&
      !isBrowserOffline() &&
      !socket.active
    ) {
      reconnectSocket();
    }
  } catch {
    if (isBrowserOffline()) {
      markConnectionLost('offline');
    } else if (useConnection.getState().status === 'connected') {
      markConnectionLost('reconnecting', true);
    }
  } finally {
    clearTimeout(timer);
    probingHealth = false;
  }
}

function start() {
  if (started) return;
  started = true;
  lastServerActivityAt = Date.now();

  const noteActivity = () => {
    lastServerActivityAt = Date.now();
  };

  socket.on('connect', () => {
    socketAlive = true;
    noteActivity();
  });
  socket.on('hello', () => {
    socketAlive = true;
    noteActivity();
    if (isBrowserOffline()) {
      useConnection.setState({ status: 'offline' });
      return;
    }
    if (!needsResync) {
      useConnection.setState({ status: 'connected' });
      void queryClient.invalidateQueries({ type: 'active' });
      return;
    }
    useConnection.setState({ status: 'reconnecting' });
    const gen = ++resyncGeneration;
    void finishResyncAndConnect(gen);
  });
  socket.on('disconnect', (reason?: string) => {
    socketAlive = false;
    if (typeof reason === 'string' && reason !== 'io client disconnect') {
      needsResync = true;
      resyncGeneration += 1;
    }
    useConnection.setState({
      status: isBrowserOffline() ? 'offline' : 'reconnecting',
    });
  });
  socket.on('connect_error', () => {
    markConnectionLost(isBrowserOffline() ? 'offline' : 'reconnecting');
  });
  socket.io?.on?.('reconnect_attempt', () => {
    if (useConnection.getState().status === 'connected') {
      markConnectionLost(isBrowserOffline() ? 'offline' : 'reconnecting');
    }
  });

  if (typeof window !== 'undefined') {
    window.addEventListener('offline', () => {
      markConnectionLost('offline');
    });
    window.addEventListener('online', () => {
      needsResync = true;
      socketAlive = false;
      resyncGeneration += 1;
      useConnection.setState({ status: 'reconnecting' });
      reconnectSocket();
    });
  }

  queryClient.getQueryCache().subscribe((event) => {
    if (event.type !== 'updated') return;
    if (event.action.type === 'success') {
      noteActivity();
      return;
    }
    if (
      event.action.type === 'error' &&
      isConnectivityError(event.action.error)
    ) {
      if (isBrowserOffline()) {
        markConnectionLost('offline');
      } else if (useConnection.getState().status === 'connected') {
        markConnectionLost('reconnecting', true);
      }
    }
  });

  socket.on('zone:update', (zone) => {
    noteActivity();
    updateZone(queryClient, zone);
  });
  const citizen = () =>
    !useSession.getState().user ||
    useSession.getState().user?.role === 'citizen';
  socket.on('zone:detail', (zone) => {
    noteActivity();
    if (!citizen()) updatePoliceZone(queryClient, zone);
  });
  socket.on('source:status', (status) => {
    noteActivity();
    if (!citizen()) updateSource(queryClient, status);
  });
  const onAlert = (alert: import('@contract/types').Alert) => {
    noteActivity();
    if (!citizen()) updateAlert(queryClient, alert);
  };
  socket.on('alert:new', onAlert);
  socket.on('alert:updated', onAlert);
  socket.on('alert:escalated', ({ alert }) => onAlert(alert));
  socket.on('advisory:new', (item) => {
    noteActivity();
    updateAdvisory(queryClient, item.id, item);
    if (citizen()) toast(item.title);
  });
  socket.on('advisory:retracted', ({ id }) => {
    noteActivity();
    updateAdvisory(queryClient, id);
    if (citizen()) toast('Advisory removed');
  });
  socket.on('report:new', (report) => {
    noteActivity();
    if (citizen()) return;
    void queryClient.invalidateQueries({
      queryKey: ['reports'],
      predicate: (q) => q.queryKey[1] !== 'banner',
    });
    if (report.kind === 'CROWD') {
      toast(`New crowd report in ${report.zone_name ?? 'venue'}`);
    }
  });
  socket.on('report:updated', (report) => {
    noteActivity();
    updateReportInCache(queryClient, report);
    void queryClient.invalidateQueries({
      queryKey: ['reports'],
      predicate: (q) => q.queryKey[1] !== 'banner',
    });
    const currentUser = useSession.getState().user;
    if (
      currentUser &&
      report.created_by.id === currentUser.id &&
      report.status !== 'PENDING'
    ) {
      const label = report.kind === 'SOS' ? 'SOS report' : 'Crowd report';
      toast(`${label} #${report.id} ${report.status.toLowerCase()}`);
    }
  });
  socket.on('auth:expired', () => {
    noteActivity();
    void refreshSession().catch(() => {});
  });

  useSession.subscribe((s, old) => {
    if (s.generation !== old.generation) useSeries.setState({ zones: {} });
    if (s.tokens?.access_token !== old.tokens?.access_token) reconnectSocket();
  });
  if (!isBrowserOffline()) {
    reconnectSocket();
  }
}

export function RealtimeProvider({ children }: { children: ReactNode }) {
  useConfig();
  useEffect(() => {
    start();
    const watchdog = setInterval(() => {
      if (
        typeof document !== 'undefined' &&
        document.visibilityState === 'hidden'
      ) {
        return;
      }
      if (isBrowserOffline()) {
        if (useConnection.getState().status !== 'offline') {
          markConnectionLost('offline');
        }
        return;
      }
      const currentStatus = useConnection.getState().status;
      if (
        currentStatus === 'connected' &&
        Date.now() - lastServerActivityAt >= SILENCE_PROBE_AFTER_MS
      ) {
        void checkBackendHealth();
      } else if (currentStatus === 'reconnecting') {
        if (!socketAlive) {
          void checkBackendHealth();
        } else if (needsResync) {
          const gen = ++resyncGeneration;
          void finishResyncAndConnect(gen);
        }
      }
    }, WATCHDOG_INTERVAL_MS);

    return () => {
      clearInterval(watchdog);
    };
  }, []);
  const status = useConnection((s) => s.status);
  return (
    <>
      {status !== 'connected' && (
        <div
          role="status"
          className="sticky top-0 z-40 bg-amber-100 p-2 text-center text-amber-950"
        >
          {status === 'offline'
            ? 'Offline / data may be stale'
            : 'Reconnecting... live data may be stale'}
        </div>
      )}
      {children}
    </>
  );
}

import { useEffect, type ReactNode } from 'react';
import { create } from 'zustand';
import { toast } from 'sonner';
import { socket } from '@/lib/socket';
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
let started = false;
function start() {
  if (started) return;
  started = true;
  socket.on('hello', () => {
    useConnection.setState({ status: 'connected' });
    void queryClient.invalidateQueries({ type: 'active' });
  });
  socket.on('disconnect', () =>
    useConnection.setState({
      status:
        typeof navigator !== 'undefined' && navigator.onLine === false
          ? 'offline'
          : 'reconnecting',
    }),
  );
  if (typeof window !== 'undefined') {
    window.addEventListener('offline', () => {
      useConnection.setState({ status: 'offline' });
    });
    window.addEventListener('online', () => {
      useConnection.setState({ status: 'reconnecting' });
      socket.disconnect();
      socket.auth = { token: useSession.getState().tokens?.access_token };
      socket.connect();
    });
  }
  socket.on('zone:update', (zone) => updateZone(queryClient, zone));
  const citizen = () =>
    !useSession.getState().user ||
    useSession.getState().user?.role === 'citizen';
  socket.on('zone:detail', (zone) => {
    if (!citizen()) updatePoliceZone(queryClient, zone);
  });
  socket.on('source:status', (status) => {
    if (!citizen()) updateSource(queryClient, status);
  });
  const onAlert = (alert: import('@contract/types').Alert) => {
    if (!citizen()) updateAlert(queryClient, alert);
  };
  socket.on('alert:new', onAlert);
  socket.on('alert:updated', onAlert);
  socket.on('alert:escalated', ({ alert }) => onAlert(alert));
  socket.on('advisory:new', (item) => {
    updateAdvisory(queryClient, item.id, item);
    if (citizen()) toast(item.title);
  });
  socket.on('advisory:retracted', ({ id }) => {
    updateAdvisory(queryClient, id);
    if (citizen()) toast('Advisory removed');
  });
  socket.on('report:new', (report) => {
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
    void refreshSession().catch(() => {});
  });
  function connect() {
    socket.disconnect();
    socket.auth = { token: useSession.getState().tokens?.access_token };
    socket.connect();
  }
  useSession.subscribe((s, old) => {
    if (s.generation !== old.generation) useSeries.setState({ zones: {} });
    if (s.tokens?.access_token !== old.tokens?.access_token) connect();
  });
  connect();
}
export function RealtimeProvider({ children }: { children: ReactNode }) {
  useConfig();
  useEffect(start, []);
  const status = useConnection((s) => s.status);
  return (
    <>
      {status !== 'connected' && (
        <div
          role="status"
          className="sticky top-0 z-40 bg-amber-100 p-2 text-center text-amber-950"
        >
          {status === 'offline'
            ? 'Offline — live data may be stale'
            : 'Reconnecting... live data may be stale'}
        </div>
      )}
      {children}
    </>
  );
}

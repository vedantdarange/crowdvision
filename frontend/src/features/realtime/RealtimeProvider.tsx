import { useEffect, type ReactNode } from 'react';
import { create } from 'zustand';
import { toast } from 'sonner';
import { socket } from '@/lib/socket';
import { queryClient } from '@/lib/queryClient';
import { useSession } from '@/features/auth';
import { refreshSession } from '@/lib/apiClient';
import { useConfig } from '@/features/zones/api';
import { updateZone, updateAdvisory } from './cache';
export const useConnection = create<{ status: 'connected' | 'reconnecting' }>(
  () => ({ status: 'reconnecting' }),
);
let started = false;
function start() {
  if (started) return;
  started = true;
  socket.on('hello', () => {
    useConnection.setState({ status: 'connected' });
    void queryClient.invalidateQueries({ type: 'active' });
  });
  socket.on('disconnect', () =>
    useConnection.setState({ status: 'reconnecting' }),
  );
  socket.on('zone:update', (zone) => updateZone(queryClient, zone));
  const citizen = () =>
    !useSession.getState().user ||
    useSession.getState().user?.role === 'citizen';
  socket.on('advisory:new', (item) => {
    updateAdvisory(queryClient, item.id, item);
    if (citizen()) toast(item.title);
  });
  socket.on('advisory:retracted', ({ id }) => {
    updateAdvisory(queryClient, id);
    if (citizen()) toast('Advisory removed');
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
      {status === 'reconnecting' && (
        <div
          role="status"
          className="sticky top-0 z-40 bg-amber-100 p-2 text-center text-amber-950"
        >
          Reconnecting... live data may be stale
        </div>
      )}
      {children}
    </>
  );
}

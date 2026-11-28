import { useEffect } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import type { Alert, ApiList, Report } from '@contract/types';
import { apiClient } from '@/lib/apiClient';
import { socket } from '@/lib/socket';
import { useSession } from '@/features/auth';

async function allPages<T>(path: string, signal: AbortSignal) {
  const rows: T[] = [];
  for (let page = 1; ; page++) {
    const response = await apiClient<ApiList<T>>(
      path + '&limit=100&page=' + page,
      { signal },
    );
    rows.push(...response.data);
    if (page >= response.pagination.total_pages) return rows;
  }
}
export function urgent(report: Report) {
  return (
    report.kind === 'SOS' &&
    ['CRUSH_RISK', 'FIRE', 'MEDICAL'].some((type) => report.sos_type === type)
  );
}
export function useBannerFeed() {
  const client = useQueryClient();
  const alerts = useQuery({
    queryKey: ['alerts', 'banner'],
    queryFn: ({ signal }) => allPages<Alert>('/alerts?status=NEW', signal),
  });
  const reports = useQuery({
    queryKey: ['reports', 'banner'],
    queryFn: async ({ signal }) =>
      (
        await allPages<Report>('/reports?kind=SOS&status=PENDING', signal)
      ).filter(urgent),
  });
  useEffect(() => {
    function canReceive() {
      const role = useSession.getState().user?.role;
      return role === 'police' || role === 'admin';
    }
    function update(r: Report) {
      if (!canReceive() || !urgent(r)) return;
      client.setQueryData<Report[]>(['reports', 'banner'], (old = []) => {
        const rows = old.filter((row) => row.id !== r.id);
        if (r.status === 'PENDING' && urgent(r)) rows.push(r);
        return rows;
      });
      void client.invalidateQueries({ queryKey: ['reports', 'banner'] });
    }
    function received(r: Report) {
      if (!canReceive() || r.kind !== 'SOS') return;
      if (!urgent(r))
        toast('SOS - ' + r.sos_type?.toLowerCase().replaceAll('_', ' '));
      update(r);
    }
    socket.on('report:new', received);
    socket.on('report:updated', update);
    return () => {
      socket.off('report:new', received);
      socket.off('report:updated', update);
    };
  }, [client]);
  // The singleton socket's alert:new/updated/escalated handlers and the queue
  // mutation both call updateAlert, so optimistic acknowledgements silence this feed too.
  return {
    alerts: alerts.data ?? [],
    reports: reports.data ?? [],
    failed: alerts.isError || reports.isError,
    retry: () => {
      void alerts.refetch();
      void reports.refetch();
    },
  };
}

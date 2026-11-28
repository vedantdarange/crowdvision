import {
  useMutation,
  useQueryClient,
  useSuspenseQuery,
} from '@tanstack/react-query';
import type {
  AnalyticsSummary,
  ApiList,
  ApiOne,
  AuditLog,
  Settings,
  User,
} from '@contract/types';
import { apiClient } from '@/lib/apiClient';
import { queryKeys as k } from '@/lib/queryKeys';
import { toast } from 'sonner';

type Filters = Record<string, string>;
function parameters(filters: Filters) {
  return new URLSearchParams(
    Object.entries(filters).filter(([, value]) => value !== ''),
  ).toString();
}
export function useUsers(filters: Filters) {
  return useSuspenseQuery({
    queryKey: k.users(filters),
    queryFn: ({ signal }) =>
      apiClient<ApiList<User>>('/users?' + parameters(filters), { signal }),
  });
}
export function useAudit(filters: Filters) {
  return useSuspenseQuery({
    queryKey: k.audit(filters),
    queryFn: ({ signal }) =>
      apiClient<ApiList<AuditLog>>('/audit-logs?' + parameters(filters), {
        signal,
      }),
  });
}
type UserWrite =
  | { id: number; body: Partial<Pick<User, 'role' | 'is_active'>> }
  | {
      id?: never;
      body: Pick<User, 'name' | 'email'> & {
        password: string;
        role: 'admin' | 'police';
      };
    };
export function useWriteUser() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: UserWrite) =>
      apiClient<ApiOne<User>>(id === undefined ? '/users' : '/users/' + id, {
        method: id === undefined ? 'POST' : 'PATCH',
        body,
      }),
    onSuccess: async (_, input) => {
      toast.success(
        input.id === undefined ? 'Account created.' : 'Account updated.',
      );
      await Promise.all(
        ['users', 'audit'].map((key) =>
          client.invalidateQueries({ queryKey: [key] }),
        ),
      );
    },
  });
}
export function useSettings() {
  return useSuspenseQuery({
    queryKey: k.settings,
    queryFn: async ({ signal }) =>
      (await apiClient<ApiOne<Settings>>('/settings', { signal })).data,
  });
}
export function useSaveSettings() {
  const client = useQueryClient();
  return useMutation({
    scope: { id: 'admin-settings' },
    mutationFn: async (body: Partial<Settings>) =>
      (
        await apiClient<ApiOne<Settings>>('/settings', {
          method: 'PATCH',
          body,
        })
      ).data,
    onSuccess: (data) => {
      client.setQueryData(k.settings, data);
      for (const key of [k.help, k.config, ['audit']])
        void client.invalidateQueries({ queryKey: key });
      toast.success('Settings saved.');
    },
  });
}
export type Range = { from: string; to: string };
export function useAnalytics(range: Range) {
  const params = parameters(range);
  return useSuspenseQuery({
    queryKey: k.analytics(params),
    queryFn: async ({ signal }) =>
      (
        await apiClient<ApiOne<AnalyticsSummary>>(
          '/analytics/summary?' + params,
          { signal },
        )
      ).data,
  });
}
export async function downloadAlerts(range: Range) {
  const blob = await apiClient<Blob>(
    '/analytics/export/alerts.csv?' + parameters(range),
    { responseType: 'blob' },
  );
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = 'alerts.csv';
  document.body.append(link);
  try {
    link.click();
  } finally {
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}

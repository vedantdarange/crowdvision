import { useRef } from 'react';
import {
  useMutation,
  useQueryClient,
  useSuspenseQuery,
  type QueryClient,
} from '@tanstack/react-query';
import { toast } from 'sonner';
import type {
  ApiList,
  ApiOne,
  Report,
  ReportKind,
  ReportStatus,
  SosType,
} from '@contract/types';
import { apiClient, ApiRequestError } from '@/lib/apiClient';
import { queryKeys as k } from '@/lib/queryKeys';
import { useSession } from '@/features/auth';

export type ReportFilters = {
  kind?: ReportKind | '';
  status?: ReportStatus | '';
  zone_id?: string;
  page: number;
  limit: number;
};

export interface SubmitCrowdReportInput {
  image: Blob;
  lat: number;
  lng: number;
  note?: string;
}

export interface SubmitSosReportInput {
  sos_type: SosType;
  lat: number;
  lng: number;
  note?: string;
}

export interface ReviewReportInput {
  report: Report;
  status: 'VERIFIED' | 'DISMISSED';
  review_note?: string;
}

export function compareReportsPendingFirst(a: Report, b: Report): number {
  const rank = (r: Report) => (r.status === 'PENDING' ? 0 : 1);
  return (
    rank(a) - rank(b) ||
    Date.parse(b.created_at) - Date.parse(a.created_at) ||
    b.id - a.id
  );
}

/** Updates matching cached report pages and lists across citizen and police views. */
export function updateReportInCache(client: QueryClient, report: Report): void {
  const patchList = (
    old: ApiList<Report> | undefined,
  ): ApiList<Report> | undefined => {
    if (!old) return old;
    if (!old.data.some((row) => row.id === report.id)) return old;
    return {
      ...old,
      data: old.data.map((row) => (row.id === report.id ? report : row)),
    };
  };

  for (const [key] of client.getQueriesData<ApiList<Report>>({
    queryKey: ['reports'],
    predicate: (q) => q.queryKey[1] !== 'banner',
  })) {
    client.setQueryData<ApiList<Report>>(key, (old) => patchList(old));
  }

  client.setQueryData<Report[]>(['reports', 'banner'], (old) => {
    if (!old) return old;
    return report.status === 'PENDING'
      ? old.map((row) => (row.id === report.id ? report : row))
      : old.filter((row) => row.id !== report.id);
  });
}

export function formatReportError(
  error: unknown,
  kind: 'CROWD' | 'SOS',
): string {
  if (!(error instanceof ApiRequestError)) {
    return 'Something went wrong while sending your report. Please try again.';
  }
  if (error.status === 413 || error.code === 'PAYLOAD_TOO_LARGE') {
    return 'Photo exceeds the 5 MB limit. Please choose or retake a smaller photo.';
  }
  if (error.status === 503 || error.code === 'DETECTOR_UNAVAILABLE') {
    return 'The crowd counter is temporarily busy or unavailable. Wait a moment and try again, or send an SOS if there is an emergency.';
  }
  if (error.status === 429 || error.code === 'RATE_LIMITED') {
    const waitText = error.retryAfterSeconds
      ? `in ${error.retryAfterSeconds} seconds`
      : kind === 'CROWD'
        ? 'in about 1 minute'
        : 'in a few minutes';
    if (kind === 'SOS') {
      return `Too many SOS reports submitted recently (limit: 3 per 10 minutes). Try again ${waitText}, or call 112 immediately if you are in danger.`;
    }
    return `You can submit 1 crowd report per minute. Please try again ${waitText}.`;
  }
  if (error.status === 422 && error.details) {
    const first = Object.values(error.details).find(
      (v) => Array.isArray(v) && typeof v[0] === 'string',
    ) as string[] | undefined;
    if (first?.[0]) return first[0];
  }
  return error.message;
}

export function useMyReports(page = 1, limit = 20) {
  return useSuspenseQuery({
    queryKey: [...k.myReports, page, limit] as const,
    queryFn: ({ signal }) =>
      apiClient<ApiList<Report>>(`/reports/mine?page=${page}&limit=${limit}`, {
        signal,
      }),
  });
}

export function useReports(filters: ReportFilters) {
  const params = new URLSearchParams();
  if (filters.kind) params.set('kind', filters.kind);
  if (filters.status) params.set('status', filters.status);
  if (filters.zone_id) params.set('zone_id', filters.zone_id);
  params.set('page', String(filters.page));
  params.set('limit', String(filters.limit));

  return useSuspenseQuery({
    queryKey: k.reports(filters),
    queryFn: ({ signal }) =>
      apiClient<ApiList<Report>>('/reports?' + params.toString(), { signal }),
  });
}

export function useSubmitCrowdReport() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (input: SubmitCrowdReportInput) => {
      const form = new FormData();
      form.append('image', input.image, 'crowd-report.jpg');
      form.append('lat', String(input.lat));
      form.append('lng', String(input.lng));
      const trimmed = input.note?.trim();
      if (trimmed) form.append('note', trimmed);

      return (
        await apiClient<ApiOne<Report>>('/reports/crowd', {
          method: 'POST',
          body: form,
        })
      ).data;
    },
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: k.myReports });
    },
  });
}

export function useSubmitSosReport() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (input: SubmitSosReportInput) => {
      const trimmed = input.note?.trim();
      return (
        await apiClient<ApiOne<Report>>('/reports/sos', {
          method: 'POST',
          body: {
            sos_type: input.sos_type,
            lat: input.lat,
            lng: input.lng,
            ...(trimmed ? { note: trimmed } : {}),
          },
        })
      ).data;
    },
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: k.myReports });
    },
  });
}

export function useReviewReport() {
  const client = useQueryClient();
  const generation = useRef(useSession.getState().generation).current;
  const sameSession = () => generation === useSession.getState().generation;

  return useMutation({
    mutationFn: async ({ report, status, review_note }: ReviewReportInput) => {
      const trimmed = review_note?.trim();
      return (
        await apiClient<ApiOne<Report>>(`/reports/${report.id}`, {
          method: 'PATCH',
          body: {
            status,
            ...(trimmed ? { review_note: trimmed } : {}),
          },
        })
      ).data;
    },
    onMutate: async ({ report, status, review_note }) => {
      await client.cancelQueries({ queryKey: ['reports'] });
      const reviewer = useSession.getState().user;
      const pages = client.getQueriesData<ApiList<Report>>({
        queryKey: ['reports'],
        predicate: (q) => q.queryKey[1] !== 'banner',
      });
      const bannerBefore = client.getQueryData<Report[]>(['reports', 'banner']);

      const optimistic: Report = {
        ...report,
        status,
        review_note: review_note?.trim() || null,
        reviewed_by: reviewer
          ? { id: reviewer.id, name: reviewer.name }
          : report.reviewed_by,
        reviewed_at: new Date().toISOString(),
      };

      if (sameSession()) {
        updateReportInCache(client, optimistic);
      }

      return {
        report,
        bannerBefore,
        bannerOptimistic: client.getQueryData<Report[]>(['reports', 'banner']),
        pages: pages.map(([key, original]) => ({
          key,
          original,
          optimistic: client.getQueryData<ApiList<Report>>(key),
        })),
      };
    },
    onError: (error, _vars, snapshot) => {
      if (!sameSession()) return;
      if (snapshot) {
        for (const page of snapshot.pages) {
          if (client.getQueryData(page.key) === page.optimistic) {
            client.setQueryData(page.key, page.original);
          }
        }
        if (
          client.getQueryData(['reports', 'banner']) ===
          snapshot.bannerOptimistic
        ) {
          client.setQueryData(['reports', 'banner'], snapshot.bannerBefore);
        }
      }
      toast.error(
        error instanceof ApiRequestError &&
          error.status === 409 &&
          error.code === 'INVALID_TRANSITION'
          ? 'Someone already reviewed this report.'
          : error instanceof Error
            ? error.message
            : 'Could not update report.',
      );
    },
    onSuccess: (updated) => {
      if (sameSession()) {
        updateReportInCache(client, updated);
      }
    },
    onSettled: () => {
      if (sameSession()) {
        void client.invalidateQueries({ queryKey: ['reports'] });
      }
    },
  });
}

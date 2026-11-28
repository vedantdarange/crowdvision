import type { ReactNode } from 'react';
import type { Pagination } from '@contract/types';
import { Button } from '@/components/ui/button';
import { SuspenseBoundary } from '@/components/SuspenseBoundary';
import { ApiRequestError } from '@/lib/apiClient';
export function ManagementPage({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="police-page min-w-0">
      <header>
        <h1>{title}</h1>
      </header>
      <SuspenseBoundary>{children}</SuspenseBoundary>
    </section>
  );
}
export function Pager({
  data,
  setPage,
}: {
  data: Pagination;
  setPage: (page: number) => void;
}) {
  return (
    <nav aria-label="Pagination" className="police-actions">
      <Button
        variant="outline"
        disabled={data.page <= 1}
        onClick={() => setPage(data.page - 1)}
      >
        Previous
      </Button>
      <span>
        Page {data.page} of {Math.max(1, data.total_pages)}
      </span>
      <Button
        variant="outline"
        disabled={data.page >= data.total_pages}
        onClick={() => setPage(data.page + 1)}
      >
        Next
      </Button>
    </nav>
  );
}
export function WriteError({ error }: { error: Error | null }) {
  if (!error) return null;
  return (
    <div role="alert">
      <p>{error.message}</p>
      {error instanceof ApiRequestError &&
        Object.entries(error.details ?? {}).map(([field, messages]) => (
          <p key={field}>
            {field}:{' '}
            {Array.isArray(messages) ? messages.join(' ') : String(messages)}
          </p>
        ))}
    </div>
  );
}

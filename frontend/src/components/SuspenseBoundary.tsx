import { Suspense, type ReactNode } from 'react';
import { ErrorBoundary } from 'react-error-boundary';
import { QueryErrorResetBoundary } from '@tanstack/react-query';
import { Skeleton } from '@/components/ui/skeleton';
import { ErrorFallback } from './ErrorFallback';
export function SuspenseBoundary({ children }: { children: ReactNode }) {
  return (
    <QueryErrorResetBoundary>
      {({ reset }) => (
        <ErrorBoundary onReset={reset} FallbackComponent={ErrorFallback}>
          <Suspense
            fallback={
              <div role="status" className="space-y-4">
                <span className="sr-only">Loading page</span>
                <Skeleton className="h-8 w-48" />
                <Skeleton className="h-48 w-full" />
              </div>
            }
          >
            {children}
          </Suspense>
        </ErrorBoundary>
      )}
    </QueryErrorResetBoundary>
  );
}

import type { FallbackProps } from 'react-error-boundary';
import { Button } from '@/components/ui/button';
export function ErrorFallback({ resetErrorBoundary }: FallbackProps) {
  return (
    <section role="alert" className="space-y-4 rounded-xl border p-6">
      <h2 className="font-semibold">Something went wrong</h2>
      <p>Please retry. If the problem continues, check your connection.</p>
      <Button onClick={resetErrorBoundary}>Retry</Button>
    </section>
  );
}

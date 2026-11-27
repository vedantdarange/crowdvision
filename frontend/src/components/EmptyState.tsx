import type { ReactNode } from 'react';
export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <section className="rounded-xl border border-dashed p-6 text-center">
      <h2 className="font-semibold">{title}</h2>
      <p className="mt-2 text-muted-foreground">{description}</p>
      {action && <div className="mt-4">{action}</div>}
    </section>
  );
}

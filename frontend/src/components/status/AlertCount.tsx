const counts = new Intl.NumberFormat('en-IN');

/** Inline zone, peak crowd count and critical count threshold. */
export function AlertCount({
  zone,
  peak,
  threshold,
}: {
  zone: string;
  peak: number | null;
  threshold: number | null;
}) {
  return (
    <>
      <strong className="font-heading font-semibold">{zone}</strong>
      {' · '}
      <span className="reading">
        {peak === null ? '—' : counts.format(peak)} /{' '}
        {threshold === null ? '—' : counts.format(threshold)}
      </span>
    </>
  );
}

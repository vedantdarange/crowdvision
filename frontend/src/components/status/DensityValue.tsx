import { formatDensity } from '@/lib/format';
export function DensityValue({ value }: { value: number | null }) {
  return (
    <span
      className="tabular-nums"
      aria-label={
        value === null
          ? 'Density unavailable'
          : `${formatDensity(value)} people per square metre`
      }
    >
      {formatDensity(value)}
      {value !== null && (
        <span className="ml-1 text-sm text-muted-foreground">people/m²</span>
      )}
    </span>
  );
}

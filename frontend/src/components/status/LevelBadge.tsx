import {
  CircleCheck,
  TriangleAlert,
  OctagonAlert,
  WifiOff,
} from 'lucide-react';
import type { Level } from '@contract/types';
const presentation = {
  SAFE: { icon: CircleCheck, text: 'Safe', style: 'bg-safe-bg text-safe' },
  WARNING: {
    icon: TriangleAlert,
    text: 'Warning',
    style: 'bg-warning-bg text-warning',
  },
  CRITICAL: {
    icon: OctagonAlert,
    text: 'Critical',
    style: 'bg-critical-bg text-critical',
  },
  NO_DATA: {
    icon: WifiOff,
    text: 'No data',
    style: 'bg-no-data-bg text-no-data',
  },
} as const;
export function LevelBadge({ level }: { level: Level }) {
  const { icon: Icon, text, style } = presentation[level];
  return (
    <span
      className={`inline-flex items-center gap-2 rounded-md px-3 py-2 text-sm font-semibold ${style}`}
    >
      <Icon aria-hidden="true" size={18} />
      <span>{text}</span>
    </span>
  );
}

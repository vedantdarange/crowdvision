import { ArrowDownRight, ArrowRight, ArrowUpRight } from 'lucide-react';
import type { Trend } from '@contract/types';
const trends = {
  RISING: { icon: ArrowUpRight, label: 'Rising' },
  STEADY: { icon: ArrowRight, label: 'Steady' },
  FALLING: { icon: ArrowDownRight, label: 'Falling' },
};
export function TrendIcon({ trend }: { trend: Trend }) {
  const { icon: Icon, label } = trends[trend];
  return (
    <span className="inline-flex items-center gap-2 text-sm">
      <Icon size={18} aria-hidden="true" />
      {label}
    </span>
  );
}

import {
  BarChart,
  Bar,
  ResponsiveContainer,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
} from 'recharts';
import type { AnalyticsSummary } from '@contract/types';
export default function AlertsByZoneChart({
  rows,
}: {
  rows: AnalyticsSummary['alerts_by_zone'];
}) {
  return (
    <div aria-hidden="true" className="h-60">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} accessibilityLayer={false}>
          <defs>
            <pattern
              id="critical-stripes"
              width="8"
              height="8"
              patternUnits="userSpaceOnUse"
            >
              <rect width="8" height="8" fill="#b91c1c" />
              <path d="M0 8L8 0" stroke="white" strokeWidth="2" />
            </pattern>
          </defs>
          <XAxis dataKey="zone_name" />
          <YAxis allowDecimals={false} />
          <Tooltip />
          <Legend />
          <Bar
            dataKey="warning"
            name="Warning"
            fill="#b45309"
            isAnimationActive={false}
          />
          <Bar
            dataKey="critical"
            name="Critical"
            fill="url(#critical-stripes)"
            isAnimationActive={false}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

import { z } from 'zod';
import type { Settings } from '@contract/types';
// Inclusive bounds from backend/app/schemas/config.py.
export const bounds = {
  detect_conf: [0.1, 0.9],
  smoothing_window: [1, 15],
  target_fps: [1, 10],
  frame_width: [320, 1280],
  jpeg_quality: [0.3, 0.95],
  stale_after_s: [3, 60],
  debounce_s: [0, 30],
  clear_s: [0, 60],
  hysteresis_ratio: [0.5, 0.99],
  cooldown_s: [0, 600],
  escalation_s: [10, 600],
  reraise_after_s: [10, 600],
  default_warning_density: [0.1, 10],
  default_critical_density: [0.1, 10],
} satisfies Record<keyof Omit<Settings, 'help_info'>, [number, number]>;
type Key = keyof typeof bounds;
export function wholeNumber(key: Key) {
  return ['smoothing_window', 'target_fps', 'frame_width'].includes(key);
}
function numberField(key: Key) {
  const [min, max] = bounds[key];
  return (wholeNumber(key) ? z.number().int() : z.number()).min(min).max(max);
}
const numericFields = Object.fromEntries(
  (Object.keys(bounds) as Key[]).map((key) => [key, numberField(key)]),
) as Record<Key, z.ZodNumber>;
export const numericSchema = z.object(numericFields);
export const thresholdsValid = (v: {
  default_warning_density: number;
  default_critical_density: number;
}) => v.default_warning_density < v.default_critical_density;
export const thresholdIssue = {
  path: ['default_warning_density'],
  message: 'Warning must be below critical.',
};
const point = z.object({
  name: z.string().min(1).max(120),
  lat: z.number().min(-90).max(90).nullable(),
  lng: z.number().min(-180).max(180).nullable(),
  note: z.string().max(500).nullable(),
});
export const helpSchema = z.object({
  emergency_numbers: z.array(
    z.object({
      label: z.string().min(1).max(100),
      number: z.string().min(1).max(50),
    }),
  ),
  medical_points: z.array(point),
  exits: z.array(point),
});

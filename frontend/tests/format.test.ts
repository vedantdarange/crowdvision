import { expect, it } from 'vitest';
import { formatDensity, relativeTime } from '@/lib/format';
it('formats density with one decimal, preserving null and zero', () => {
  expect(formatDensity(null)).toBe('—');
  expect(formatDensity(0)).toBe('0.0');
  expect(formatDensity(3.46)).toBe('3.5');
});
it('formats elapsed time and absent/invalid/future timestamps', () => {
  const now = Date.parse('2026-11-24T10:15:30Z');
  expect(relativeTime('2026-11-24T10:15:18Z', now)).toBe('12 s ago');
  expect(relativeTime('2026-11-24T10:13:30Z', now)).toBe('2 min ago');
  expect(relativeTime('2026-11-24T08:15:30Z', now)).toBe('2 h ago');
  expect(relativeTime('2026-11-22T10:15:30Z', now)).toBe('2 d ago');
  expect(relativeTime(null, now)).toBe('No data yet');
  expect(relativeTime('bad', now)).toBe('Unknown time');
  expect(relativeTime('2026-11-24T11:15:30Z', now)).toBe('0 s ago');
});

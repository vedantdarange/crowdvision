import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { axe } from 'vitest-axe';
import { LevelBadge } from '@/components/status/LevelBadge';
import { AlertCount } from '@/components/status/AlertCount';
import { DensityValue } from '@/components/status/DensityValue';
import { TrendIcon } from '@/components/status/TrendIcon';
import { ThemeProvider, useTheme } from '@/app/ThemeProvider';
import type { Level } from '@contract/types';

describe('status components', () => {
  it('groups alert counts and distinguishes zero from a missing threshold', () => {
    const { container, rerender } = render(
      <AlertCount zone="Stage Area" peak={4820} threshold={4000} />,
    );
    expect(container).toHaveTextContent('Stage Area · 4,820 / 4,000');
    rerender(<AlertCount zone="Stage Area" peak={0} threshold={null} />);
    expect(container).toHaveTextContent('Stage Area · 0 / —');
  });
  it.each<[Level, string]>([
    ['SAFE', 'Safe'],
    ['WARNING', 'Warning'],
    ['CRITICAL', 'Critical'],
    ['NO_DATA', 'No data'],
  ])(
    '%s has an icon, visible text and no axe violations',
    async (level, label) => {
      const { container } = render(<LevelBadge level={level} />);
      expect(screen.getByText(label)).toBeVisible();
      expect(container.querySelector('svg')).toHaveAttribute(
        'aria-hidden',
        'true',
      );
      // jsdom has no layout/canvas engine. Contrast is calculated separately from CSS tokens.
      expect(
        (
          await axe(container, {
            rules: { 'color-contrast': { enabled: false } },
          })
        ).violations,
      ).toEqual([]);
    },
  );
  it('distinguishes unavailable density from zero and labels the trend', () => {
    const { rerender } = render(<DensityValue value={null} />);
    expect(screen.getByLabelText('Density unavailable')).toHaveTextContent('—');
    rerender(
      <>
        <DensityValue value={0} />
        <TrendIcon trend="RISING" />
      </>,
    );
    expect(screen.getByLabelText('0.0 people per square metre')).toBeVisible();
    expect(screen.getByText('Rising')).toBeVisible();
  });
});
function Toggle() {
  const { theme, toggle } = useTheme();
  return <button onClick={toggle}>{theme}</button>;
}
it('defaults to the workspace theme and remembers an explicit preference', async () => {
  localStorage.clear();
  const { unmount } = render(
    <ThemeProvider defaultTheme="dark">
      <Toggle />
    </ThemeProvider>,
  );
  await userEvent.click(screen.getByRole('button', { name: 'dark' }));
  expect(document.documentElement).not.toHaveClass('dark');
  expect(localStorage.getItem('crowd-safety-theme')).toBe('light');
  unmount();
  render(
    <ThemeProvider defaultTheme="dark">
      <Toggle />
    </ThemeProvider>,
  );
  expect(screen.getByRole('button', { name: 'light' })).toBeVisible();
  localStorage.clear();
});

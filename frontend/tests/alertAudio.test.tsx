import { StrictMode } from 'react';
import { act, renderHook } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { useAlertAudio } from '@/features/alerts/useAlertAudio';
import { useAlertTitle } from '@/features/alerts/useAlertTitle';

const frequencies = vi.fn(),
  stop = vi.fn(),
  close = vi.fn(async () => {});
class Device {
  static latest: Device;
  constructor() {
    Device.latest = this;
  }
  state = 'suspended';
  currentTime = 0;
  onstatechange: (() => void) | null = null;
  resume = async () => {
    this.state = 'running';
    this.onstatechange?.();
  };
  close = close;
  createGain = () => ({
    connect: vi.fn(),
    disconnect: vi.fn(),
    gain: { setValueAtTime: vi.fn(), exponentialRampToValueAtTime: vi.fn() },
  });
  createOscillator = () => ({
    connect: vi.fn(),
    disconnect: vi.fn(),
    frequency: { setValueAtTime: frequencies },
    start: vi.fn(),
    stop,
  });
}
function setup() {
  vi.useFakeTimers();
  vi.stubGlobal('AudioContext', Device);
  vi.stubGlobal('Notification', {
    requestPermission: vi.fn(async () => 'granted'),
  });
  return renderHook(({ c, w }) => useAlertAudio(c, w), {
    initialProps: { c: '', w: '' },
    wrapper: StrictMode,
  });
}
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  localStorage.clear();
});
const sirens = () => frequencies.mock.calls.filter(([hz]) => hz === 990).length;
it('arms in one gesture, repeats critical sirens until acknowledgement, and caps each incident at 60 seconds', async () => {
  const h = setup();
  const vibrate = vi.fn();
  vi.stubGlobal('navigator', { vibrate });
  h.rerender({ c: 'a1', w: '' });
  expect(sirens()).toBe(0);
  await act(async () => h.result.current.arm());
  expect(Notification.requestPermission).toHaveBeenCalledTimes(1);
  expect(vibrate).toHaveBeenCalledWith(30);
  expect(vibrate).toHaveBeenCalledWith([300, 100, 300]);
  expect(h.result.current.armed).toBe(true);
  expect(sirens()).toBe(1);
  act(() => vi.advanceTimersByTime(10000));
  expect(sirens()).toBe(2);
  h.rerender({ c: '', w: '' });
  expect(stop).toHaveBeenLastCalledWith();
  act(() => vi.advanceTimersByTime(30000));
  expect(sirens()).toBe(2);
  h.rerender({ c: 'r2', w: '' });
  act(() => vi.advanceTimersByTime(90000));
  expect(sirens()).toBe(8);
  h.unmount();
  expect(close).toHaveBeenCalledTimes(1);
  expect(vi.getTimerCount()).toBe(0);
  const reload = setup();
  expect(reload.result.current.intent).toBe(true);
  expect(reload.result.current.armed).toBe(false);
});
it('chimes once for a warning, remembers mute and releases an active repeat on unmount', async () => {
  const h = setup();
  await act(async () => h.result.current.arm());
  frequencies.mockClear();
  h.rerender({ c: '', w: 'a2' });
  act(() => vi.advanceTimersByTime(20000));
  expect(frequencies.mock.calls).toEqual([[550, 0]]);
  h.rerender({ c: 'a2', w: '' });
  act(() => h.result.current.toggleMute());
  act(() => vi.advanceTimersByTime(10000));
  expect(sirens()).toBe(1);
  h.unmount();
  expect(vi.getTimerCount()).toBe(0);
  expect(setup().result.current.muted).toBe(true);
});
it.each([false, true])(
  'emphasizes the title and restores it with reduced motion %s',
  (reduced) => {
    vi.useFakeTimers();
    vi.stubGlobal('matchMedia', () => ({ matches: reduced }));
    document.title = 'Operations';
    const h = renderHook(() => useAlertTitle(2), { wrapper: StrictMode });
    expect(document.title).toBe('(2 awaiting review) Operations');
    act(() => vi.advanceTimersByTime(1200));
    expect(document.title).toBe(
      reduced ? '(2 awaiting review) Operations' : 'Operations',
    );
    h.unmount();
    expect(document.title).toBe('Operations');
    expect(vi.getTimerCount()).toBe(0);
  },
);

it('requires another tap when the browser suspends its audio context', async () => {
  const h = setup();
  await act(async () => h.result.current.arm());
  act(() => {
    Device.latest.state = 'suspended';
    Device.latest.onstatechange?.();
  });
  expect(h.result.current.armed).toBe(false);
  await act(async () => h.result.current.arm());
  expect(h.result.current.armed).toBe(true);
  h.unmount();
  expect(Device.latest.onstatechange).toBeNull();
});

import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it, vi } from 'vitest';
import { setupPwaRegistration } from '@/features/push/registerPwa';
import {
  buildNotificationSpec,
  handleNotificationClick,
  handlePushEvent,
  isExcludedFromSwCache,
  type SwClientsLike,
  type SwWindowClientLike,
} from '@/features/push/swHandlers';

function collectSourceFiles(dir: string): string[] {
  const results: string[] = [];
  for (const entry of readdirSync(dir)) {
    const fullPath = join(dir, entry);
    const stat = statSync(fullPath);
    if (stat.isDirectory()) {
      results.push(...collectSourceFiles(fullPath));
    } else if (/\.(ts|tsx|js|jsx|mjs)$/.test(entry)) {
      results.push(fullPath);
    }
  }
  return results;
}

describe('service worker push handlers', () => {
  it('always shows a generic fallback notification on invalid JSON payloads', async () => {
    const showNotification = vi.fn().mockResolvedValue(undefined);
    let pending: Promise<unknown> | undefined;

    handlePushEvent(
      {
        data: { text: () => 'not-valid-json{{{' },
        waitUntil: (promise) => {
          pending = promise;
        },
      },
      { showNotification },
    );

    await pending;
    expect(showNotification).toHaveBeenCalledTimes(1);
    const [title, options] = showNotification.mock.calls[0] as [
      string,
      Record<string, unknown>,
    ];
    expect(title).toBe('Crowd Safety Monitor');
    expect(options.tag).toBe('crowd-safety-fallback');
    expect(options.requireInteraction).toBe(false);
    expect(options.data).toEqual({ url: '/police' });
  });

  it('always shows a fallback notification when push data is missing', async () => {
    const showNotification = vi.fn().mockResolvedValue(undefined);
    let pending: Promise<unknown> | undefined;

    handlePushEvent(
      {
        data: null,
        waitUntil: (promise) => {
          pending = promise;
        },
      },
      { showNotification },
    );

    await pending;
    expect(showNotification).toHaveBeenCalledTimes(1);
    expect(showNotification.mock.calls[0]?.[0]).toBe('Crowd Safety Monitor');
  });

  it('preserves tag and sets requireInteraction only for CRITICAL alerts and SOS reports', async () => {
    const showNotification = vi.fn().mockResolvedValue(undefined);
    const waitList: Promise<unknown>[] = [];

    handlePushEvent(
      {
        data: {
          text: () =>
            JSON.stringify({
              kind: 'ALERT',
              title: 'WARNING — South Lawn',
              body: '3.10 people/m2',
              url: '/police/alerts?focus=a1',
              tag: 'zone:z2:ALERT',
              level: 'WARNING',
              alert_id: 'a1',
              zone_id: 'z2',
            }),
        },
        waitUntil: (p) => waitList.push(p),
      },
      { showNotification },
    );

    handlePushEvent(
      {
        data: {
          text: () =>
            JSON.stringify({
              kind: 'ALERT',
              title: 'CRITICAL — Gate B East',
              body: '4.25 people/m2 — Deploy stewards',
              url: '/police/alerts?focus=a2',
              tag: 'zone:z1:ALERT',
              level: 'CRITICAL',
              alert_id: 'a2',
              zone_id: 'z1',
            }),
        },
        waitUntil: (p) => waitList.push(p),
      },
      { showNotification },
    );

    handlePushEvent(
      {
        data: {
          text: () =>
            JSON.stringify({
              kind: 'SOS',
              title: 'SOS report — North Plaza',
              body: 'Crowd crushing near barriers',
              url: '/police/reports?focus=rep-99',
              tag: 'report:rep-99',
              report_id: 'rep-99',
              zone_id: 'z3',
            }),
        },
        waitUntil: (p) => waitList.push(p),
      },
      { showNotification },
    );

    await Promise.all(waitList);
    expect(showNotification).toHaveBeenCalledTimes(3);

    const warningOpts = showNotification.mock.calls[0]?.[1] as {
      tag: string;
      requireInteraction: boolean;
      data: { url: string };
    };
    expect(warningOpts.tag).toBe('zone:z2:ALERT');
    expect(warningOpts.requireInteraction).toBe(false);
    expect(warningOpts.data).toEqual({ url: '/police/alerts?focus=a1' });

    const criticalOpts = showNotification.mock.calls[1]?.[1] as {
      tag: string;
      requireInteraction: boolean;
      vibrate: number[];
      data: { url: string };
    };
    expect(criticalOpts.tag).toBe('zone:z1:ALERT');
    expect(criticalOpts.requireInteraction).toBe(true);
    expect(criticalOpts.vibrate.length).toBeGreaterThan(0);
    expect(criticalOpts.data).toEqual({ url: '/police/alerts?focus=a2' });

    const sosOpts = showNotification.mock.calls[2]?.[1] as {
      tag: string;
      requireInteraction: boolean;
      data: { url: string };
    };
    expect(sosOpts.tag).toBe('report:rep-99');
    expect(sosOpts.requireInteraction).toBe(true);
    expect(sosOpts.data).toEqual({ url: '/police/reports?focus=rep-99' });
  });

  it('rejects cross-origin redirect urls in notification payloads', () => {
    const spec = buildNotificationSpec(
      JSON.stringify({
        kind: 'SOS',
        title: 'Test',
        body: 'Body',
        url: 'https://evil.example/steal',
      }),
    );
    expect(spec.options.data.url).toBe('/police/reports');
  });
});

describe('service worker notificationclick routing', () => {
  it('closes the notification, focuses an existing same-origin client, and navigates to data.url', async () => {
    const focus = vi.fn().mockResolvedValue(undefined);
    const navigate = vi.fn().mockResolvedValue(undefined);
    const openWindow = vi.fn().mockResolvedValue(undefined);
    const close = vi.fn();

    const existingClient: SwWindowClientLike = {
      url: 'https://monitor.local/police',
      focused: true,
      focus,
      navigate,
    };
    const clients: SwClientsLike = {
      matchAll: vi.fn().mockResolvedValue([existingClient]),
      openWindow,
    };

    let pending: Promise<unknown> | undefined;
    handleNotificationClick(
      {
        notification: { data: { url: '/police/reports?focus=rep-7' }, close },
        waitUntil: (p) => {
          pending = p;
        },
      },
      clients,
      'https://monitor.local',
    );

    await pending;
    expect(close).toHaveBeenCalledTimes(1);
    expect(focus).toHaveBeenCalledTimes(1);
    expect(navigate).toHaveBeenCalledWith(
      'https://monitor.local/police/reports?focus=rep-7',
    );
    expect(openWindow).not.toHaveBeenCalled();
  });

  it('opens a new window when no same-origin window client exists', async () => {
    const openWindow = vi.fn().mockResolvedValue(undefined);
    const close = vi.fn();
    const clients: SwClientsLike = {
      matchAll: vi.fn().mockResolvedValue([
        {
          url: 'https://other-origin.example/foo',
          focus: vi.fn(),
        },
      ]),
      openWindow,
    };

    let pending: Promise<unknown> | undefined;
    handleNotificationClick(
      {
        notification: { data: { url: '/police/alerts?focus=a9' }, close },
        waitUntil: (p) => {
          pending = p;
        },
      },
      clients,
      'https://monitor.local',
    );

    await pending;
    expect(close).toHaveBeenCalledTimes(1);
    expect(openWindow).toHaveBeenCalledWith(
      'https://monitor.local/police/alerts?focus=a9',
    );
  });
});

describe('service worker cache denylist and update lifecycle', () => {
  it('never intercepts /api or /socket.io navigations', () => {
    expect(isExcludedFromSwCache('/api')).toBe(true);
    expect(isExcludedFromSwCache('/api/v1/zones/live')).toBe(true);
    expect(isExcludedFromSwCache('/socket.io')).toBe(true);
    expect(isExcludedFromSwCache('/socket.io/')).toBe(true);
    expect(isExcludedFromSwCache('/')).toBe(false);
    expect(isExcludedFromSwCache('/police')).toBe(false);
    expect(isExcludedFromSwCache('/police/alerts')).toBe(false);
  });

  it('registers SW immediately, applies waiting updates, and checks updates on visibility change', async () => {
    const update = vi.fn().mockResolvedValue(undefined);
    const updateSw = vi.fn().mockResolvedValue(undefined);
    let capturedOnNeedRefresh: (() => void) | undefined;
    let capturedOnRegistered:
      | ((url: string, reg: ServiceWorkerRegistration | undefined) => void)
      | undefined;
    let appliedUpdateFn: (() => Promise<void>) | undefined;

    const cleanup = setupPwaRegistration({
      registerFn: (opts) => {
        capturedOnNeedRefresh = opts?.onNeedRefresh;
        capturedOnRegistered = opts?.onRegisteredSW;
        return updateSw;
      },
      onUpdateAvailable: (applyUpdate) => {
        appliedUpdateFn = applyUpdate;
      },
    });

    capturedOnRegistered?.('/sw.js', {
      update,
    } as unknown as ServiceWorkerRegistration);
    capturedOnNeedRefresh?.();
    expect(appliedUpdateFn).toBeTypeOf('function');

    await appliedUpdateFn?.();
    expect(updateSw).toHaveBeenCalledWith(true);

    Object.defineProperty(document, 'visibilityState', {
      value: 'visible',
      configurable: true,
    });
    document.dispatchEvent(new Event('visibilitychange'));
    expect(update).toHaveBeenCalledTimes(1);

    cleanup();
  });

  it('has zero direct new Notification(...) calls anywhere in frontend/src', () => {
    const srcRoot = join(process.cwd(), 'src');
    const files = collectSourceFiles(srcRoot);
    expect(files.length).toBeGreaterThan(10);

    const forbidden = new RegExp(
      'new\\s+(?:(?:window|globalThis)\\.)?Notification\\s*\\(',
    );
    const offenders: string[] = [];
    for (const file of files) {
      const content = readFileSync(file, 'utf8');
      if (forbidden.test(content)) {
        offenders.push(file);
      }
    }
    expect(offenders).toEqual([]);
  });
});

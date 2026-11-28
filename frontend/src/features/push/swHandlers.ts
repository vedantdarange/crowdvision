import type { Level } from '@contract/types';

export const API_OR_SOCKET_DENYLIST: readonly RegExp[] = [
  /^\/api(?:\/|$)/,
  /^\/socket\.io(?:\/|$)/,
];

export function isExcludedFromSwCache(pathname: string): boolean {
  return API_OR_SOCKET_DENYLIST.some((pattern) => pattern.test(pathname));
}

export interface SwNotificationSpec {
  title: string;
  options: {
    body: string;
    icon: string;
    badge: string;
    tag: string;
    requireInteraction: boolean;
    renotify: boolean;
    vibrate: number[];
    data: { url: string };
  };
}

export interface SwRegistrationLike {
  showNotification(title: string, options?: unknown): Promise<void>;
}

export interface SwPushEventLike {
  data?: { text(): string } | null;
  waitUntil(promise: Promise<unknown>): void;
}

export interface SwWindowClientLike {
  url: string;
  focused?: boolean;
  focus?: () => Promise<unknown>;
  navigate?: (url: string) => Promise<unknown>;
}

export interface SwClientsLike {
  matchAll(options?: {
    type?: 'window' | 'worker' | 'sharedworker' | 'all';
    includeUncontrolled?: boolean;
  }): Promise<readonly SwWindowClientLike[]>;
  openWindow(url: string): Promise<unknown>;
}

export interface SwNotificationClickEventLike {
  notification: {
    data?: unknown;
    close(): void;
  };
  waitUntil(promise: Promise<unknown>): void;
}

interface RawPushPayload {
  kind?: unknown;
  title?: unknown;
  body?: unknown;
  url?: unknown;
  tag?: unknown;
  level?: unknown;
  alert_id?: unknown;
  report_id?: unknown;
  zone_id?: unknown;
}

function readNonEmptyString(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : undefined;
}

export function sanitizeTargetUrl(
  rawUrl: unknown,
  fallback = '/police',
  origin = 'https://crowd.local',
): string {
  const candidate = readNonEmptyString(rawUrl);
  if (!candidate) return fallback;
  if (candidate.startsWith('/') && !candidate.startsWith('//')) {
    return candidate;
  }
  try {
    const parsed = new URL(candidate, origin);
    if (parsed.origin === origin) {
      return `${parsed.pathname}${parsed.search}${parsed.hash}`;
    }
  } catch {
    return fallback;
  }
  return fallback;
}

export function parsePushPayload(
  rawText: string | null | undefined,
): RawPushPayload | null {
  if (!rawText) return null;
  try {
    const parsed: unknown = JSON.parse(rawText);
    if (
      typeof parsed === 'object' &&
      parsed !== null &&
      !Array.isArray(parsed)
    ) {
      return parsed as RawPushPayload;
    }
  } catch {
    return null;
  }
  return null;
}

export function buildNotificationSpec(
  rawText: string | null | undefined,
): SwNotificationSpec {
  const payload = parsePushPayload(rawText);
  if (!payload) {
    return {
      title: 'Crowd Safety Monitor',
      options: {
        body: 'Open Crowd Safety Monitor to view the latest alert.',
        icon: '/icons/icon-192.png',
        badge: '/icons/icon-192.png',
        tag: 'crowd-safety-fallback',
        requireInteraction: false,
        renotify: false,
        vibrate: [200, 100, 200],
        data: { url: '/police' },
      },
    };
  }

  const kind = readNonEmptyString(payload.kind);
  const level = readNonEmptyString(payload.level) as Level | undefined;
  const zoneId = readNonEmptyString(payload.zone_id);
  const reportId = readNonEmptyString(payload.report_id);
  const fallbackUrl = kind === 'SOS' ? '/police/reports' : '/police';
  const url = sanitizeTargetUrl(payload.url, fallbackUrl);
  const title =
    readNonEmptyString(payload.title) ??
    (kind === 'SOS' ? 'SOS report received' : 'Crowd Safety Monitor');
  const body =
    readNonEmptyString(payload.body) ??
    'Open Crowd Safety Monitor for details.';
  const tag =
    readNonEmptyString(payload.tag) ??
    (kind === 'SOS' && reportId
      ? `report:${reportId}`
      : zoneId
        ? `zone:${zoneId}:${kind ?? 'ALERT'}`
        : 'crowd-safety-alert');
  const requireInteraction = level === 'CRITICAL' || kind === 'SOS';

  return {
    title,
    options: {
      body,
      icon: '/icons/icon-192.png',
      badge: '/icons/icon-192.png',
      tag,
      requireInteraction,
      renotify: requireInteraction,
      vibrate: requireInteraction ? [300, 120, 300, 120, 400] : [200, 100, 200],
      data: { url },
    },
  };
}

/** Handles Web Push events and always shows a visible notification. */
export function handlePushEvent(
  event: SwPushEventLike,
  registration: SwRegistrationLike,
): void {
  let rawText: string | null = null;
  try {
    rawText = event.data ? event.data.text() : null;
  } catch {
    rawText = null;
  }
  const spec = buildNotificationSpec(rawText);
  event.waitUntil(registration.showNotification(spec.title, spec.options));
}

/** Focuses and navigates an existing same-origin window, or opens a new one. */
export function handleNotificationClick(
  event: SwNotificationClickEventLike,
  clients: SwClientsLike,
  origin: string,
): void {
  event.notification.close();
  const data = event.notification.data as { url?: unknown } | null | undefined;
  const targetPath = sanitizeTargetUrl(data?.url, '/police', origin);
  const targetUrl = new URL(targetPath, origin).href;

  event.waitUntil(
    (async () => {
      const windowClients = await clients.matchAll({
        type: 'window',
        includeUncontrolled: true,
      });
      const sameOriginClients = windowClients.filter((client) => {
        try {
          return new URL(client.url).origin === origin;
        } catch {
          return false;
        }
      });
      const existing =
        sameOriginClients.find((client) => client.url === targetUrl) ??
        sameOriginClients.find((client) => client.focused) ??
        sameOriginClients[0];

      if (existing && typeof existing.focus === 'function') {
        try {
          await existing.focus();
          if (
            typeof existing.navigate === 'function' &&
            existing.url !== targetUrl
          ) {
            await existing.navigate(targetUrl);
          }
          return;
        } catch {
          // Fall back to opening a fresh window if focusing/navigating fails.
        }
      }
      await clients.openWindow(targetUrl);
    })(),
  );
}

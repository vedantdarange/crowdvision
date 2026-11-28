import { useCallback, useEffect, useRef, useState } from 'react';
import { useConfig } from '@/features/zones/api';
import { useSession } from '@/features/auth';
import {
  deletePushSubscription,
  peekServiceWorkerRegistration,
  registerPushSubscription,
  waitForServiceWorkerRegistration,
} from './pushApi';
import { extractPushSubscription, urlBase64ToUint8Array } from './vapid';

export type WebPushStatus = 'unsupported' | 'off' | 'on' | 'blocked';

export const PUSH_SUBSCRIBE_TIMEOUT_MS = 8_000;

export interface WebPushState {
  status: WebPushStatus;
  supported: boolean;
  busy: boolean;
  canRetry?: boolean;
  notice: string | null;
  subscribe: (permissionHint?: NotificationPermission) => Promise<boolean>;
  unsubscribe: () => Promise<void>;
  reportPermission: (permission: NotificationPermission) => void;
}

class PushTimeoutError extends Error {
  constructor() {
    super('Background push setup timed out.');
    this.name = 'PushTimeoutError';
  }
}

function withTimeout<T>(
  promise: Promise<T>,
  timeoutMs: number,
  onTimeout: () => void,
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => {
      onTimeout();
      reject(new PushTimeoutError());
    }, timeoutMs);
    promise.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (err) => {
        clearTimeout(timer);
        reject(err);
      },
    );
  });
}

function hasBrowserPushApis(): boolean {
  return (
    typeof navigator !== 'undefined' &&
    typeof window !== 'undefined' &&
    'serviceWorker' in navigator &&
    'PushManager' in window &&
    'Notification' in window
  );
}

function getNotificationPermission(): NotificationPermission | 'unsupported' {
  if (typeof Notification === 'undefined') return 'unsupported';
  return Notification.permission;
}

/** Manages browser Web Push capability detection, subscription, and status notices. */
export function useWebPush(
  subscribeTimeoutMs = PUSH_SUBSCRIBE_TIMEOUT_MS,
): WebPushState {
  const hasApis = hasBrowserPushApis();
  const config = useConfig(hasApis);
  const vapidKey = config.data?.vapid_public_key ?? null;
  const configMissingKey = config.isSuccess && !vapidKey;
  const supported = hasApis && Boolean(vapidKey);
  const sessionGeneration = useSession((s) => s.generation);

  const [permission, setPermission] = useState<
    NotificationPermission | 'unsupported'
  >(getNotificationPermission);
  const [subscribed, setSubscribed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [canRetry, setCanRetry] = useState(false);
  const [runtimeNotice, setRuntimeNotice] = useState<string | null>(null);

  const mountedRef = useRef(true);
  const attemptRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      attemptRef.current += 1;
      abortRef.current?.abort();
      abortRef.current = null;
    };
  }, []);

  useEffect(() => {
    attemptRef.current += 1;
    abortRef.current?.abort();
    abortRef.current = null;
    setBusy(false);
    setCanRetry(false);
    setRuntimeNotice(null);
    setSubscribed(false);
  }, [sessionGeneration]);

  useEffect(() => {
    setPermission(getNotificationPermission());
    if (!hasApis) {
      setSubscribed(false);
      return;
    }

    let cancelled = false;
    void (async () => {
      try {
        const reg = await peekServiceWorkerRegistration();
        const sub = await reg?.pushManager?.getSubscription();
        if (!cancelled) {
          setSubscribed(Boolean(sub));
        }
      } catch {
        if (!cancelled) setSubscribed(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [hasApis, vapidKey, sessionGeneration]);

  const subscribe = useCallback(
    async (permissionHint?: NotificationPermission): Promise<boolean> => {
      if (!hasBrowserPushApis()) {
        setRuntimeNotice(
          'Background notifications are unsupported in this browser. In-app banner and siren stay active.',
        );
        return false;
      }
      if (!vapidKey) {
        setRuntimeNotice(
          'Background push is disabled on this server. In-app banner and siren stay active.',
        );
        return false;
      }

      const initialSession = useSession.getState();
      const startGeneration = initialSession.generation;
      const startUserId = initialSession.user?.id ?? null;
      const startRole = initialSession.user?.role;
      if (
        !initialSession.tokens?.access_token ||
        (startRole !== 'police' && startRole !== 'admin')
      ) {
        setRuntimeNotice(
          'Sign in with a police or admin account to enable background push. In-app alerts remain active.',
        );
        return false;
      }

      const myAttempt = ++attemptRef.current;
      abortRef.current?.abort();
      const abortController = new AbortController();
      abortRef.current = abortController;
      let timedOut = false;

      const sessionStillValid = () => {
        const cur = useSession.getState();
        return (
          cur.generation === startGeneration &&
          cur.user !== null &&
          cur.user.id === startUserId &&
          Boolean(cur.tokens?.access_token) &&
          (cur.user.role === 'police' || cur.user.role === 'admin')
        );
      };

      const attemptStillValid = () =>
        mountedRef.current &&
        attemptRef.current === myAttempt &&
        !timedOut &&
        sessionStillValid();

      setBusy(true);
      setCanRetry(false);
      setRuntimeNotice(null);

      try {
        let currentPermission = permissionHint ?? Notification.permission;
        if (currentPermission === 'default' && Notification.requestPermission) {
          currentPermission = await Notification.requestPermission();
        }
        if (!attemptStillValid()) return false;
        setPermission(currentPermission);

        if (currentPermission === 'denied') {
          setSubscribed(false);
          return false;
        }
        if (currentPermission !== 'granted') {
          return false;
        }

        const runSubscribe = async (): Promise<boolean> => {
          const registration = await waitForServiceWorkerRegistration();
          if (!attemptStillValid()) return false;
          if (!registration?.pushManager) {
            setRuntimeNotice(
              'Service worker is not active yet. In-app alerts and siren remain active.',
            );
            setCanRetry(true);
            return false;
          }

          let sub = await registration.pushManager.getSubscription();
          if (!attemptStillValid()) return false;

          if (!sub) {
            const applicationServerKey = urlBase64ToUint8Array(vapidKey);
            const pendingSub = registration.pushManager.subscribe({
              userVisibleOnly: true,
              applicationServerKey,
            });
            pendingSub
              .then((lateSub) => {
                // If session logged out or changed while browser subscribe hung, detach the orphan.
                const cur = useSession.getState();
                if (
                  cur.user === null ||
                  (cur.generation !== startGeneration && !cur.tokens)
                ) {
                  void lateSub?.unsubscribe().catch(() => undefined);
                }
              })
              .catch(() => undefined);
            sub = await pendingSub;
          }

          if (!attemptStillValid()) return false;

          const payload = extractPushSubscription(sub);
          await registerPushSubscription(payload, abortController.signal);
          if (!attemptStillValid()) return false;

          setSubscribed(true);
          setCanRetry(false);
          return true;
        };

        return await withTimeout(runSubscribe(), subscribeTimeoutMs, () => {
          timedOut = true;
          abortController.abort();
        });
      } catch (error) {
        if (mountedRef.current && sessionStillValid()) {
          const latestAttempt = attemptRef.current === myAttempt;
          if (error instanceof PushTimeoutError || latestAttempt) {
            setCanRetry(true);
            setRuntimeNotice(
              error instanceof PushTimeoutError
                ? 'Background push setup timed out. In-app banner and siren remain active — retry when ready.'
                : 'Could not finish background push setup. In-app banner and siren remain active.',
            );
          }
        }
        return false;
      } finally {
        if (abortRef.current === abortController) {
          abortRef.current = null;
        }
        if (
          mountedRef.current &&
          (attemptRef.current === myAttempt || timedOut)
        ) {
          setBusy(false);
        }
      }
    },
    [subscribeTimeoutMs, vapidKey],
  );

  const reportPermission = useCallback((next: NotificationPermission) => {
    setPermission(next);
    if (next === 'denied') {
      setSubscribed(false);
    }
  }, []);

  const unsubscribe = useCallback(async (): Promise<void> => {
    if (!hasBrowserPushApis()) return;
    setBusy(true);
    try {
      const registration = await peekServiceWorkerRegistration();
      const sub = await registration?.pushManager?.getSubscription();
      if (!sub) {
        setSubscribed(false);
        return;
      }
      await deletePushSubscription(sub.endpoint).catch(() => undefined);
      await sub.unsubscribe().catch(() => false);
      setSubscribed(false);
      setRuntimeNotice(null);
    } finally {
      setBusy(false);
    }
  }, []);

  let status: WebPushStatus;
  if (!hasApis || configMissingKey) {
    status = 'unsupported';
  } else if (permission === 'denied') {
    status = 'blocked';
  } else if (subscribed) {
    status = 'on';
  } else {
    status = 'off';
  }

  let defaultNotice: string | null = null;
  if (status === 'blocked') {
    defaultNotice =
      'Notifications are blocked in your browser site settings. Allow notifications for this site and reload to receive background alerts.';
  } else if (status === 'unsupported') {
    defaultNotice = !hasApis
      ? 'Background push is unsupported here (or requires HTTPS / installed app); in-app banner and siren still work.'
      : 'Background push is disabled on this server (no VAPID key); in-app banner and siren still work.';
  }

  return {
    status,
    supported,
    busy,
    canRetry,
    notice: runtimeNotice ?? defaultNotice,
    subscribe,
    unsubscribe,
    reportPermission,
  };
}

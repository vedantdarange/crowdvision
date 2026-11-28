import { useCallback, useEffect, useState } from 'react';
import { useConfig } from '@/features/zones/api';
import {
  deletePushSubscription,
  peekServiceWorkerRegistration,
  registerPushSubscription,
  waitForServiceWorkerRegistration,
} from './pushApi';
import { extractPushSubscription, urlBase64ToUint8Array } from './vapid';

export type WebPushStatus = 'unsupported' | 'off' | 'on' | 'blocked';

export interface WebPushState {
  status: WebPushStatus;
  supported: boolean;
  busy: boolean;
  notice: string | null;
  subscribe: (permissionHint?: NotificationPermission) => Promise<boolean>;
  unsubscribe: () => Promise<void>;
  reportPermission: (permission: NotificationPermission) => void;
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
export function useWebPush(): WebPushState {
  const hasApis = hasBrowserPushApis();
  const config = useConfig(hasApis);
  const vapidKey = config.data?.vapid_public_key ?? null;
  const configMissingKey = config.isSuccess && !vapidKey;
  const supported = hasApis && Boolean(vapidKey);

  const [permission, setPermission] = useState<
    NotificationPermission | 'unsupported'
  >(getNotificationPermission);
  const [subscribed, setSubscribed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [runtimeNotice, setRuntimeNotice] = useState<string | null>(null);

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
  }, [hasApis, vapidKey]);

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

      setBusy(true);
      setRuntimeNotice(null);
      try {
        let currentPermission = permissionHint ?? Notification.permission;
        if (currentPermission === 'default' && Notification.requestPermission) {
          currentPermission = await Notification.requestPermission();
        }
        setPermission(currentPermission);

        if (currentPermission === 'denied') {
          setSubscribed(false);
          return false;
        }
        if (currentPermission !== 'granted') {
          return false;
        }

        const registration = await waitForServiceWorkerRegistration();
        if (!registration?.pushManager) {
          setRuntimeNotice(
            'Service worker is not active yet. In-app alerts and siren remain active.',
          );
          return false;
        }

        let sub = await registration.pushManager.getSubscription();
        if (!sub) {
          const applicationServerKey = urlBase64ToUint8Array(vapidKey);
          sub = await registration.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey,
          });
        }

        const payload = extractPushSubscription(sub);
        await registerPushSubscription(payload);
        setSubscribed(true);
        return true;
      } catch {
        setRuntimeNotice(
          'Could not finish background push setup. In-app banner and siren remain active.',
        );
        return false;
      } finally {
        setBusy(false);
      }
    },
    [vapidKey],
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
    notice: runtimeNotice ?? defaultNotice,
    subscribe,
    unsubscribe,
    reportPermission,
  };
}

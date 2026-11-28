import type { ApiOne, Role } from '@contract/types';
import { apiClient } from '@/lib/apiClient';
import { request } from '@/lib/request';
import type { PushSubscriptionInput } from './vapid';

export async function registerPushSubscription(
  payload: PushSubscriptionInput,
): Promise<{ id: string }> {
  const response = await apiClient<ApiOne<{ id: string }>>(
    '/push/subscriptions',
    {
      method: 'POST',
      body: payload,
    },
  );
  return response.data;
}

export async function deletePushSubscription(
  endpoint: string,
  token?: string,
): Promise<void> {
  const path = '/push/subscriptions?endpoint=' + encodeURIComponent(endpoint);
  if (token) {
    await request<void>(path, { method: 'DELETE', token });
    return;
  }
  await apiClient<void>(path, { method: 'DELETE' });
}

export async function sendTestPush(): Promise<{ sent: number }> {
  const response = await apiClient<ApiOne<{ sent: number }>>('/push/test', {
    method: 'POST',
  });
  return response.data;
}

export async function peekServiceWorkerRegistration(): Promise<ServiceWorkerRegistration | null> {
  if (typeof navigator === 'undefined' || !('serviceWorker' in navigator)) {
    return null;
  }
  if (typeof navigator.serviceWorker.getRegistration === 'function') {
    try {
      const reg = await navigator.serviceWorker.getRegistration();
      if (reg) return reg;
    } catch {
      return null;
    }
  }
  return null;
}

/** Returns active registration or waits briefly for serviceWorker.ready without hanging in dev. */
export async function waitForServiceWorkerRegistration(
  timeoutMs = 1500,
): Promise<ServiceWorkerRegistration | null> {
  if (typeof navigator === 'undefined' || !('serviceWorker' in navigator)) {
    return null;
  }
  const existing = await peekServiceWorkerRegistration();
  if (existing) return existing;

  const readyPromise = navigator.serviceWorker.ready;
  if (!readyPromise) return null;

  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      readyPromise.catch(() => null),
      new Promise<null>((resolve) => {
        timer = setTimeout(() => resolve(null), timeoutMs);
      }),
    ]);
  } finally {
    if (timer !== undefined) clearTimeout(timer);
  }
}

/** Unsubscribes the current browser device from Web Push on logout. */
export async function unsubscribePushOnLogout(
  token: string | undefined,
  role: Role | undefined,
): Promise<void> {
  if (typeof navigator === 'undefined' || typeof window === 'undefined') {
    return;
  }
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
    return;
  }

  let reg: ServiceWorkerRegistration | null = null;
  try {
    reg = await peekServiceWorkerRegistration();
  } catch {
    return;
  }
  if (!reg?.pushManager) return;

  let sub: PushSubscription | null = null;
  try {
    sub = await reg.pushManager.getSubscription();
  } catch {
    return;
  }
  if (!sub) return;

  const endpoint = sub.endpoint;
  const tasks: Promise<unknown>[] = [sub.unsubscribe().catch(() => false)];
  if (token && (role === 'police' || role === 'admin') && endpoint) {
    tasks.push(deletePushSubscription(endpoint, token).catch(() => undefined));
  }
  await Promise.all(tasks);
}

export interface PushSubscriptionInput {
  endpoint: string;
  keys: {
    p256dh: string;
    auth: string;
  };
}

/** Converts a base64url-encoded VAPID public key into an ArrayBuffer-backed Uint8Array. */
export function urlBase64ToUint8Array(
  base64UrlString: string,
): Uint8Array<ArrayBuffer> {
  const cleaned = base64UrlString.trim();
  if (!cleaned || !/^[A-Za-z0-9_-]+=*$/.test(cleaned)) {
    throw new Error('Invalid VAPID public key format.');
  }
  const padding = '='.repeat((4 - (cleaned.length % 4)) % 4);
  const base64 = (cleaned + padding).replace(/-/g, '+').replace(/_/g, '/');
  const raw = atob(base64);
  const bytes = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i += 1) {
    bytes[i] = raw.charCodeAt(i);
  }
  return bytes;
}

export function arrayBufferToBase64Url(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  for (let i = 0; i < bytes.length; i += 1) {
    binary += String.fromCharCode(bytes[i] ?? 0);
  }
  return btoa(binary)
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/g, '');
}

/** Extracts endpoint and p256dh/auth keys from a browser PushSubscription. */
export function extractPushSubscription(
  subscription: PushSubscription,
): PushSubscriptionInput {
  const endpoint = subscription.endpoint?.trim();
  if (!endpoint) {
    throw new Error('Push subscription is missing an endpoint.');
  }

  const jsonKeys =
    typeof subscription.toJSON === 'function'
      ? subscription.toJSON().keys
      : undefined;

  let p256dh = jsonKeys?.p256dh ?? '';
  let auth = jsonKeys?.auth ?? '';

  if ((!p256dh || !auth) && typeof subscription.getKey === 'function') {
    const p256dhBuf = subscription.getKey('p256dh');
    const authBuf = subscription.getKey('auth');
    if (p256dhBuf && !p256dh) p256dh = arrayBufferToBase64Url(p256dhBuf);
    if (authBuf && !auth) auth = arrayBufferToBase64Url(authBuf);
  }

  if (!p256dh || !auth) {
    throw new Error('Push subscription is missing encryption keys.');
  }

  return {
    endpoint,
    keys: { p256dh, auth },
  };
}

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import {
  act,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { axe } from 'vitest-axe';
import alertsFixture from '../../contract/examples/alert.json';
import configFixture from '../../contract/examples/config.json';
import seedUser from '../../contract/examples/user.json';
import type { Alert } from '@contract/types';
import { AppShell } from '@/app/layouts/AppShell';
import { AlertCenter } from '@/features/alerts/AlertCenter';
import { useSession } from '@/features/auth';
import {
  InstallHint,
  PUSH_SUBSCRIBE_TIMEOUT_MS,
  isIosSafari,
  urlBase64ToUint8Array,
  useWebPush,
} from '@/features/push';

const toastMock = vi.hoisted(() =>
  Object.assign(vi.fn(), {
    success: vi.fn(),
    error: vi.fn(),
  }),
);
vi.mock('sonner', () => ({ toast: toastMock }));

// 65-byte uncompressed P-256 public key in base64url (starts with 0x04 byte).
const SAMPLE_VAPID_KEY =
  'BEl62iUYgUivxIkv69yViEuiBIa-Ib9-SkvMeAtA3LFgDzkrxZJjSgSnfckjBJuBkr3qBUYIHBQFLXYp5Nksh8U';

const origNotificationDesc = Object.getOwnPropertyDescriptor(
  globalThis,
  'Notification',
);
const origPushManagerDesc = Object.getOwnPropertyDescriptor(
  window,
  'PushManager',
);
const origSwDesc = Object.getOwnPropertyDescriptor(navigator, 'serviceWorker');
const origMatchMediaDesc = Object.getOwnPropertyDescriptor(
  window,
  'matchMedia',
);
const origAudioContextDesc = Object.getOwnPropertyDescriptor(
  window,
  'AudioContext',
);

class MockAudioContext {
  state = 'suspended';
  currentTime = 0;
  onstatechange: (() => void) | null = null;
  resume = vi.fn(async () => {
    this.state = 'running';
    this.onstatechange?.();
  });
  close = vi.fn(async () => {});
  createGain = () => ({
    connect: vi.fn(),
    disconnect: vi.fn(),
    gain: { setValueAtTime: vi.fn(), exponentialRampToValueAtTime: vi.fn() },
  });
  createOscillator = () => ({
    connect: vi.fn(),
    disconnect: vi.fn(),
    frequency: { setValueAtTime: vi.fn() },
    start: vi.fn(),
    stop: vi.fn(),
  });
}

function restoreGlobals() {
  if (origNotificationDesc) {
    Object.defineProperty(globalThis, 'Notification', origNotificationDesc);
  } else {
    delete (globalThis as Record<string, unknown>).Notification;
  }
  if (origPushManagerDesc) {
    Object.defineProperty(window, 'PushManager', origPushManagerDesc);
  } else {
    delete (window as unknown as Record<string, unknown>).PushManager;
  }
  if (origSwDesc) {
    Object.defineProperty(navigator, 'serviceWorker', origSwDesc);
  } else {
    delete (navigator as unknown as Record<string, unknown>).serviceWorker;
  }
  if (origMatchMediaDesc) {
    Object.defineProperty(window, 'matchMedia', origMatchMediaDesc);
  }
  if (origAudioContextDesc) {
    Object.defineProperty(window, 'AudioContext', origAudioContextDesc);
  } else {
    delete (window as unknown as Record<string, unknown>).AudioContext;
  }
}

function makeSubscription(
  endpoint = 'https://push.example/sub/1',
  unsubscribe = vi.fn().mockResolvedValue(true),
) {
  return {
    endpoint,
    unsubscribe,
    toJSON: () => ({
      endpoint,
      keys: {
        p256dh: 'p256dh_key_value',
        auth: 'auth_secret_value',
      },
    }),
  } as unknown as PushSubscription;
}

function installPushGlobals({
  permission = 'default' as NotificationPermission,
  requestPermissionResult = 'granted' as NotificationPermission,
  initialSub = null as PushSubscription | null,
  subscribeResult = makeSubscription(),
}: {
  permission?: NotificationPermission;
  requestPermissionResult?: NotificationPermission;
  initialSub?: PushSubscription | null;
  subscribeResult?: PushSubscription;
} = {}) {
  let currentPerm = permission;
  let currentSub = initialSub;

  const requestPermission = vi.fn(async () => {
    currentPerm = requestPermissionResult;
    return requestPermissionResult;
  });

  const MockNotification = {
    get permission() {
      return currentPerm;
    },
    requestPermission,
  };
  Object.defineProperty(globalThis, 'Notification', {
    value: MockNotification,
    configurable: true,
    writable: true,
  });

  Object.defineProperty(window, 'PushManager', {
    value: function PushManager() {},
    configurable: true,
  });

  const getSubscription = vi.fn(async () => currentSub);
  const subscribe = vi.fn(async (options?: PushSubscriptionOptionsInit) => {
    void options;
    currentSub = subscribeResult;
    return subscribeResult;
  });

  const registration = {
    pushManager: { getSubscription, subscribe },
    showNotification: vi.fn().mockResolvedValue(undefined),
    update: vi.fn().mockResolvedValue(undefined),
  } as unknown as ServiceWorkerRegistration;

  Object.defineProperty(navigator, 'serviceWorker', {
    value: {
      getRegistration: vi.fn().mockResolvedValue(registration),
      ready: Promise.resolve(registration),
    },
    configurable: true,
  });

  return { requestPermission, getSubscription, subscribe, registration };
}

function createQueryWrapper(vapidPublicKey: string | null = SAMPLE_VAPID_KEY) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  client.setQueryData(['config'], {
    ...configFixture,
    vapid_public_key: vapidPublicKey,
  });
  return {
    client,
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  };
}

describe('urlBase64ToUint8Array', () => {
  it('decodes base64url VAPID key into expected byte length and header byte', () => {
    const bytes = urlBase64ToUint8Array(SAMPLE_VAPID_KEY);
    expect(bytes).toBeInstanceOf(Uint8Array);
    expect(bytes.length).toBe(65);
    expect(bytes[0]).toBe(0x04);
  });

  it('rejects empty or non-base64url input', () => {
    expect(() => urlBase64ToUint8Array('')).toThrow();
    expect(() => urlBase64ToUint8Array('invalid!@#$')).toThrow();
  });
});

describe('useWebPush state machine', () => {
  beforeEach(() => {
    toastMock.mockClear();
    toastMock.success.mockClear();
    toastMock.error.mockClear();
    useSession.setState({
      user: { ...seedUser, role: 'police' },
      tokens: { access_token: 'tok-police', refresh_token: 'ref-police' },
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    sessionStorage.clear();
    restoreGlobals();
    useSession.setState({ user: null, tokens: null });
  });

  it('reports unsupported when config.vapid_public_key is null', () => {
    installPushGlobals();
    const { wrapper } = createQueryWrapper(null);
    const { result } = renderHook(() => useWebPush(), { wrapper });
    expect(result.current.status).toBe('unsupported');
    expect(result.current.supported).toBe(false);
    expect(result.current.notice).toMatch(/in-app banner and siren/i);
  });

  it('reports unsupported when PushManager or serviceWorker is unavailable', () => {
    installPushGlobals();
    delete (window as unknown as Record<string, unknown>).PushManager;
    const { wrapper } = createQueryWrapper(SAMPLE_VAPID_KEY);
    const { result } = renderHook(() => useWebPush(), { wrapper });
    expect(result.current.status).toBe('unsupported');
  });

  it('reports blocked with site settings instructions when permission is denied', () => {
    installPushGlobals({ permission: 'denied' });
    const { wrapper } = createQueryWrapper(SAMPLE_VAPID_KEY);
    const { result } = renderHook(() => useWebPush(), { wrapper });
    expect(result.current.status).toBe('blocked');
    expect(result.current.notice).toMatch(/blocked.*settings/i);
  });

  it('subscribes with userVisibleOnly + applicationServerKey and posts to /push/subscriptions', async () => {
    const sub = makeSubscription('https://push.example/device-a');
    const globals = installPushGlobals({
      permission: 'default',
      requestPermissionResult: 'granted',
      subscribeResult: sub,
    });
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ data: { id: 'sub-1' } }), {
        status: 201,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    const { wrapper } = createQueryWrapper(SAMPLE_VAPID_KEY);
    const { result } = renderHook(() => useWebPush(), { wrapper });
    expect(result.current.status).toBe('off');

    let ok = false;
    await act(async () => {
      ok = await result.current.subscribe();
    });

    expect(ok).toBe(true);
    expect(result.current.status).toBe('on');
    expect(globals.subscribe).toHaveBeenCalledTimes(1);
    const subArg = globals.subscribe.mock.calls[0]?.[0] as {
      userVisibleOnly: boolean;
      applicationServerKey: Uint8Array;
    };
    expect(subArg.userVisibleOnly).toBe(true);
    expect(Array.from(subArg.applicationServerKey)).toEqual(
      Array.from(urlBase64ToUint8Array(SAMPLE_VAPID_KEY)),
    );

    expect(fetchSpy).toHaveBeenCalledWith(
      '/api/v1/push/subscriptions',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          endpoint: 'https://push.example/device-a',
          keys: { p256dh: 'p256dh_key_value', auth: 'auth_secret_value' },
        }),
      }),
    );
  });
});

describe('ArmAlertsButton, logout cleanup, test notification menu, and InstallHint', () => {
  beforeEach(() => {
    toastMock.mockClear();
    toastMock.success.mockClear();
    toastMock.error.mockClear();
    sessionStorage.clear();
    useSession.setState({
      user: { ...seedUser, role: 'police' },
      tokens: { access_token: 'tok-police', refresh_token: 'ref-police' },
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    sessionStorage.clear();
    restoreGlobals();
    useSession.setState({ user: null, tokens: null });
  });

  it('arms alerts and subscribes to Web Push on a single tap with 0 axe violations', async () => {
    Object.defineProperty(window, 'AudioContext', {
      value: MockAudioContext,
      configurable: true,
    });
    const globals = installPushGlobals({
      permission: 'default',
      requestPermissionResult: 'granted',
    });
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockImplementation(async (input) => {
        const url = String(input);
        if (url.includes('/push/subscriptions')) {
          return new Response(JSON.stringify({ data: { id: 'sub-9' } }), {
            status: 201,
            headers: { 'Content-Type': 'application/json' },
          });
        }
        return new Response(
          JSON.stringify({
            data: [alertsFixture],
            pagination: { total: 1, page: 1, limit: 20, total_pages: 1 },
          }),
          {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          },
        );
      });

    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity } },
    });
    client.setQueryData(['config'], {
      ...configFixture,
      vapid_public_key: SAMPLE_VAPID_KEY,
    });
    client.setQueryData(['alerts', 'banner'], [alertsFixture as Alert]);

    const router = createMemoryRouter(
      [
        {
          path: '/police',
          element: (
            <main>
              <AlertCenter />
            </main>
          ),
        },
      ],
      { initialEntries: ['/police'] },
    );

    const { container } = render(
      <QueryClientProvider client={client}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );

    expect(screen.getByText('Push: Off')).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole('button', { name: /Alerts not armed/i }),
    );

    await waitFor(() => {
      expect(screen.getByText('Alerts armed')).toBeInTheDocument();
      expect(screen.getByText('Push: On')).toBeInTheDocument();
    });
    expect(globals.requestPermission).toHaveBeenCalledTimes(1);
    expect(fetchSpy).toHaveBeenCalledWith(
      '/api/v1/push/subscriptions',
      expect.objectContaining({ method: 'POST' }),
    );
    expect((await axe(container)).violations).toEqual([]);
  });

  it('shows blocked state when permission is denied during arm tap', async () => {
    installPushGlobals({
      permission: 'default',
      requestPermissionResult: 'denied',
    });

    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity } },
    });
    client.setQueryData(['config'], {
      ...configFixture,
      vapid_public_key: SAMPLE_VAPID_KEY,
    });
    client.setQueryData(['alerts', 'banner'], []);

    render(
      <QueryClientProvider client={client}>
        <AlertCenter />
      </QueryClientProvider>,
    );

    await userEvent.click(
      screen.getByRole('button', { name: /Alerts not armed/i }),
    );

    await waitFor(() => {
      expect(screen.getByText('Push: Blocked')).toBeInTheDocument();
    });
    expect(screen.getByRole('status')).toHaveTextContent(
      /blocked in your browser site settings/i,
    );
  });

  it('unsubscribes locally and calls DELETE /push/subscriptions?endpoint= on logout', async () => {
    const unsubscribe = vi.fn().mockResolvedValue(true);
    const activeSub = makeSubscription(
      'https://push.example/sub?token=abc&x=1',
      unsubscribe,
    );
    installPushGlobals({
      permission: 'granted',
      initialSub: activeSub,
    });

    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(new Response(null, { status: 204 }));

    useSession.getState().logout();

    await waitFor(() => {
      expect(unsubscribe).toHaveBeenCalledTimes(1);
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/v1/push/subscriptions?endpoint=' +
          encodeURIComponent('https://push.example/sub?token=abc&x=1'),
        expect.objectContaining({
          method: 'DELETE',
        }),
      );
      const init = fetchSpy.mock.calls[0]?.[1];
      expect(new Headers(init?.headers).get('Authorization')).toBe(
        'Bearer tok-police',
      );
    });
  });

  it('triggers POST /push/test from user menu and toasts delivered count', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ data: { sent: 3 } }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity } },
    });
    const router = createMemoryRouter(
      [
        {
          path: '/police',
          element: (
            <AppShell audience="police">
              <div>Police content</div>
            </AppShell>
          ),
        },
      ],
      { initialEntries: ['/police'] },
    );

    render(
      <QueryClientProvider client={client}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );

    await userEvent.click(screen.getByRole('button', { name: /Account for/i }));
    await userEvent.click(
      await screen.findByRole('menuitem', { name: /Send test notification/i }),
    );

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/v1/push/test',
        expect.objectContaining({ method: 'POST' }),
      );
      expect(toastMock.success).toHaveBeenCalledWith(
        'Sent test notification to 3 devices.',
      );
    });
  });

  it('renders Android beforeinstallprompt install action and iOS Safari Share guidance safely', async () => {
    Object.defineProperty(window, 'matchMedia', {
      value: vi.fn().mockReturnValue({ matches: false }),
      configurable: true,
    });

    const { container, rerender } = render(
      <main>
        <InstallHint />
      </main>,
    );
    expect(screen.queryByText(/Install Crowd Safety Monitor/i)).toBeNull();

    const promptSpy = vi.fn().mockResolvedValue(undefined);
    const installEvent = new Event('beforeinstallprompt') as Event & {
      prompt: () => Promise<void>;
      userChoice: Promise<{ outcome: 'accepted'; platform: string }>;
    };
    installEvent.prompt = promptSpy;
    installEvent.userChoice = Promise.resolve({
      outcome: 'accepted',
      platform: 'android',
    });

    act(() => {
      window.dispatchEvent(installEvent);
    });

    expect(
      screen.getByRole('button', { name: /Install app/i }),
    ).toBeInTheDocument();
    expect((await axe(container)).violations).toEqual([]);

    fireEvent.click(screen.getByRole('button', { name: /Install app/i }));
    await waitFor(() => expect(promptSpy).toHaveBeenCalledTimes(1));

    // Verify iOS Safari detection helper and hint rendering.
    expect(
      isIosSafari(
        'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
        5,
      ),
    ).toBe(true);
    expect(
      isIosSafari(
        'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/120.0.0.0 Mobile/15E148 Safari/604.1',
        5,
      ),
    ).toBe(false);

    vi.spyOn(navigator, 'userAgent', 'get').mockReturnValue(
      'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
    );
    rerender(
      <main>
        <InstallHint key="ios" />
      </main>,
    );
    expect(
      screen.getByText(/Share -> Add to Home Screen/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/iOS 16\.4\+/i)).toBeInTheDocument();
  });

  it('bounds push setup wait and lets late timeout completion fail safely without registering', async () => {
    expect(PUSH_SUBSCRIBE_TIMEOUT_MS).toBeLessThanOrEqual(10_000);

    let resolveLateSub!: (sub: PushSubscription) => void;
    const latePromise = new Promise<PushSubscription>((resolve) => {
      resolveLateSub = resolve;
    });
    const globals = installPushGlobals({ permission: 'granted' });
    globals.registration.pushManager.subscribe = vi.fn(() => latePromise);

    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ data: { id: 'sub-retry' } }), {
        status: 201,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    const { wrapper } = createQueryWrapper(SAMPLE_VAPID_KEY);
    const { result } = renderHook(() => useWebPush(50), { wrapper });

    let ok = true;
    await act(async () => {
      ok = await result.current.subscribe('granted');
    });

    expect(ok).toBe(false);
    expect(result.current.busy).toBe(false);
    expect(result.current.canRetry).toBe(true);
    expect(result.current.status).toBe('off');
    expect(result.current.notice).toMatch(/timed out.*banner and siren/i);
    expect(fetchSpy).not.toHaveBeenCalled();

    // Late completion after timeout must NOT register against the backend or turn status On.
    await act(async () => {
      resolveLateSub(
        makeSubscription('https://push.example/late-after-timeout'),
      );
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(result.current.status).toBe('off');

    // Retrying cleanly with a working subscription succeeds.
    const workingSub = makeSubscription('https://push.example/retry-ok');
    globals.registration.pushManager.subscribe = vi.fn(async () => workingSub);
    let retryOk = false;
    await act(async () => {
      retryOk = await result.current.subscribe('granted');
    });
    expect(retryOk).toBe(true);
    expect(result.current.status).toBe('on');
    expect(result.current.canRetry).toBe(false);
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });

  it('prevents a pending push subscription from registering after logout or session switch', async () => {
    let resolvePendingSub!: (sub: PushSubscription) => void;
    const pendingPromise = new Promise<PushSubscription>((resolve) => {
      resolvePendingSub = resolve;
    });
    const orphanUnsub = vi.fn().mockResolvedValue(true);
    const globals = installPushGlobals({ permission: 'granted' });
    globals.registration.pushManager.subscribe = vi.fn(() => pendingPromise);

    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ data: { id: 'sub-wrong' } }), {
        status: 201,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    const { wrapper } = createQueryWrapper(SAMPLE_VAPID_KEY);
    const { result } = renderHook(() => useWebPush(500), { wrapper });

    let subPromise!: Promise<boolean>;
    act(() => {
      subPromise = result.current.subscribe('granted');
    });
    expect(result.current.busy).toBe(true);
    await waitFor(() =>
      expect(globals.registration.pushManager.subscribe).toHaveBeenCalledTimes(
        1,
      ),
    );

    // Log out before browser pushManager.subscribe resolves.
    act(() => {
      useSession.getState().logout();
    });

    await act(async () => {
      resolvePendingSub(
        makeSubscription('https://push.example/orphan', orphanUnsub),
      );
      await subPromise;
    });

    expect(fetchSpy).not.toHaveBeenCalled();
    expect(result.current.status).toBe('off');
    await waitFor(() => expect(orphanUnsub).toHaveBeenCalledTimes(1));

    // Also verify switching directly to a different user rejects the earlier attempt.
    let resolveSwitched!: (sub: PushSubscription) => void;
    const subscribeMock2 = vi.fn(
      () =>
        new Promise<PushSubscription>((resolve) => {
          resolveSwitched = resolve;
        }),
    );
    globals.registration.pushManager.subscribe = subscribeMock2;
    act(() => {
      useSession.getState().signIn({
        access_token: 'tok-a',
        refresh_token: 'ref-a',
        expires_in: 900,
        user: { ...seedUser, id: 10, role: 'police' },
      });
    });

    let switchPromise!: Promise<boolean>;
    act(() => {
      switchPromise = result.current.subscribe('granted');
    });
    await waitFor(() => expect(subscribeMock2).toHaveBeenCalledTimes(1));
    act(() => {
      useSession.getState().signIn({
        access_token: 'tok-b',
        refresh_token: 'ref-b',
        expires_in: 900,
        user: { ...seedUser, id: 11, role: 'police' },
      });
    });

    await act(async () => {
      resolveSwitched(makeSubscription('https://push.example/stale-user-a'));
      await switchPromise;
    });

    expect(fetchSpy).not.toHaveBeenCalled();
    expect(result.current.status).toBe('off');
  });
});

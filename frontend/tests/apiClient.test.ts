import { beforeAll, afterAll, afterEach, expect, it } from 'vitest';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { apiClient, ApiRequestError } from '@/lib/apiClient';
import { useSession } from '@/features/auth/session';
import seedUser from '../../contract/examples/user.json';
import zones from '../../contract/examples/zones_live.json';
import alerts from '../../contract/examples/alerts_list.json';
import validation from '../../contract/examples/error_validation.json';
const server = setupServer();
beforeAll(() => server.listen({ onUnhandledFrame: 'error' }));
afterEach(() => {
  server.resetHandlers();
  useSession.getState().logout();
});
afterAll(() => server.close());
it('preserves single and paginated envelopes', async () => {
  server.use(
    http.get('*/api/v1/zones/live', () => HttpResponse.json(zones)),
    http.get('*/api/v1/alerts', () => HttpResponse.json(alerts)),
  );
  expect(await apiClient('/zones/live')).toEqual(zones);
  expect(await apiClient('/alerts')).toEqual(alerts);
});
it('maps contract error status, code, message and details', async () => {
  server.use(
    http.post('*/api/v1/zones', () =>
      HttpResponse.json(validation, { status: 422 }),
    ),
  );
  try {
    await apiClient('/zones', { method: 'POST', body: {} });
    expect.unreachable();
  } catch (error) {
    expect(error).toBeInstanceOf(ApiRequestError);
    expect(error).toMatchObject({ status: 422, ...validation.error });
  }
});
it('adds bearer and JSON headers, and handles a 204 response', async () => {
  server.use(
    http.delete('*/api/v1/advisories/1', async ({ request }) => {
      expect(request.headers.get('authorization')).toBe('Bearer mock.token');
      expect(request.headers.get('content-type')).toBe('application/json');
      expect(await request.json()).toEqual({ note: 'test' });
      return new HttpResponse(null, { status: 204 });
    }),
  );
  expect(
    await apiClient('/advisories/1', {
      method: 'DELETE',
      token: 'mock.token',
      body: { note: 'test' },
    }),
  ).toBeUndefined();
});
it('lets the browser set the multipart boundary', async () => {
  server.use(
    http.post('*/api/v1/reports/crowd', async ({ request }) => {
      expect(request.headers.get('content-type')).toContain(
        'multipart/form-data; boundary=',
      );
      expect((await request.formData()).get('note')).toBe('Queue');
      return HttpResponse.json({ data: { id: 1 } });
    }),
  );
  const body = new FormData();
  body.append('note', 'Queue');
  await apiClient('/reports/crowd', {
    method: 'POST',
    body,
    headers: { 'Content-Type': 'application/json' },
  });
});
it('surfaces anonymous 401 without refreshing', async () => {
  let calls = 0;
  server.use(
    http.get('*/api/v1/auth/me', () => {
      calls++;
      return HttpResponse.json(
        { error: { code: 'UNAUTHENTICATED', message: 'Sign in' } },
        { status: 401 },
      );
    }),
  );
  await expect(apiClient('/auth/me')).rejects.toMatchObject({
    status: 401,
    code: 'UNAUTHENTICATED',
  });
  expect(calls).toBe(1);
});
const unauthorized = () =>
  HttpResponse.json(
    { error: { code: 'UNAUTHENTICATED', message: 'Expired' } },
    { status: 401 },
  );
it.each([true, false])(
  'shares refresh across three 401s (refresh succeeds: %s)',
  async (success) => {
    useSession.getState().signIn({
      user: { ...seedUser, role: 'admin' },
      access_token: 'old',
      refresh_token: 'refresh',
      expires_in: 1,
    });
    window.history.replaceState(null, '', '/admin/zones?view=list#top');
    const redirects: string[] = [];
    const onExpired = (event: Event) =>
      redirects.push((event as CustomEvent<string>).detail);
    window.addEventListener('cv:session-expired', onExpired);
    let failures = 0,
      retries = 0,
      refreshes = 0;
    let release!: () => void;
    const allFailed = new Promise<void>((resolve) => {
      release = resolve;
    });
    server.use(
      http.get('*/api/v1/zones', ({ request }) => {
        if (request.headers.get('authorization') === 'Bearer new') {
          retries++;
          return HttpResponse.json(zones);
        }
        if (++failures === 3) release();
        return unauthorized();
      }),
      http.post('*/api/v1/auth/refresh', async ({ request }) => {
        refreshes++;
        expect(request.headers.get('authorization')).toBe('Bearer refresh');
        await allFailed;
        return success
          ? HttpResponse.json({
              data: { access_token: 'new', expires_in: 3600 },
            })
          : unauthorized();
      }),
    );
    try {
      const results = await Promise.allSettled(
        Array.from({ length: 3 }, () => apiClient('/zones')),
      );
      expect(results.map((r) => r.status)).toEqual(
        Array(3).fill(success ? 'fulfilled' : 'rejected'),
      );
      expect([failures, refreshes, retries]).toEqual([3, 1, success ? 3 : 0]);
      expect(redirects).toEqual(
        success ? [] : ['/login?next=%2Fadmin%2Fzones%3Fview%3Dlist%23top'],
      );
      expect(useSession.getState().tokens?.access_token ?? null).toBe(
        success ? 'new' : null,
      );
      if (!success) expect(localStorage.getItem('cv-auth')).toBeNull();
    } finally {
      window.removeEventListener('cv:session-expired', onExpired);
      window.history.replaceState(null, '', '/');
    }
  },
);

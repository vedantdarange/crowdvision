import { beforeAll, afterAll, afterEach, expect, it } from 'vitest';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { apiClient, ApiRequestError } from '@/lib/apiClient';
import zones from '../../contract/examples/zones_live.json';
import alerts from '../../contract/examples/alerts_list.json';
import validation from '../../contract/examples/error_validation.json';
const server = setupServer();
beforeAll(() => server.listen({ onUnhandledFrame: 'error' }));
afterEach(() => server.resetHandlers());
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
it('surfaces 401 once without pretending to refresh in F0', async () => {
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

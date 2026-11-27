// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { io, type Socket } from 'socket.io-client';
import type { AddressInfo } from 'node:net';
import type {
  ApiOne,
  AuthSession,
  FrameResult,
  HelloPayload,
  Alert,
  ZoneState,
} from '../../contract/types';
import { createMockServer } from '../mock-server/server';

let server: ReturnType<typeof createMockServer>, base: string;
const sockets: Socket[] = [];
beforeEach(async () => {
  server = createMockServer({ timers: false });
  await new Promise<void>((resolve) =>
    server.http.listen(0, '127.0.0.1', resolve),
  );
  base = `http://127.0.0.1:${(server.http.address() as AddressInfo).port}`;
});
afterEach(async () => {
  sockets.splice(0).forEach((s) => s.disconnect());
  await server.close();
});
async function request(
  path: string,
  method = 'GET',
  body?: unknown,
  token?: string,
) {
  return fetch(base + '/api/v1' + path, {
    method,
    headers: {
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}
async function login(email = 'police1@demo.local') {
  const res = await request('/auth/login', 'POST', {
    email,
    password: 'Demo@1234',
  });
  expect(res.status).toBe(200);
  return ((await res.json()) as ApiOne<AuthSession>).data;
}
function next<T>(socket: Socket, event: string) {
  return new Promise<T>((resolve, reject) => {
    const timeout = setTimeout(
      () => reject(new Error('Missing event: ' + event)),
      3000,
    );
    socket.once(event, (payload: T) => {
      clearTimeout(timeout);
      resolve(payload);
    });
  });
}
async function connect(token?: string) {
  const socket = io(base, {
    auth: token ? { token } : {},
    transports: ['websocket'],
    autoConnect: false,
  });
  sockets.push(socket);
  const hello = next<HelloPayload>(socket, 'hello');
  socket.connect();
  return { socket, hello: await hello };
}

describe('mock REST contract', () => {
  it('logs in all four seed accounts and enforces role boundaries', async () => {
    for (const [email, role] of [
      ['admin@demo.local', 'admin'],
      ['police1@demo.local', 'police'],
      ['police2@demo.local', 'police'],
      ['citizen@demo.local', 'citizen'],
    ])
      expect((await login(email)).user.role).toBe(role);
    expect((await request('/zones')).status).toBe(401);
    const citizen = await login('citizen@demo.local');
    expect(
      (await request('/zones', 'GET', undefined, citizen.access_token)).status,
    ).toBe(403);
    const police = await login();
    expect(
      (await request('/users', 'GET', undefined, police.access_token)).status,
    ).toBe(403);
    const data = await (await request('/zones/live')).json();
    expect(data.data).toHaveLength(3);
    expect(data.data[0]).not.toHaveProperty('count');
    expect(data.data[0]).not.toHaveProperty('sources');
    expect(data.data[0].updated_at).toBeNull();
  });
  it('registers citizens, rejects duplicate/invalid forms, refreshes and rechecks disabled users', async () => {
    const created = await request('/auth/register', 'POST', {
      name: 'Riya',
      email: 'riya@example.test',
      password: 'password1',
      role: 'admin',
    });
    expect(created.status).toBe(201);
    expect((await created.json()).data.user.role).toBe('citizen');
    expect(
      (
        await request('/auth/register', 'POST', {
          name: 'Riya',
          email: 'riya@example.test',
          password: 'password1',
        })
      ).status,
    ).toBe(409);
    const invalid = await request('/auth/register', 'POST', {});
    expect(invalid.status).toBe(422);
    expect((await invalid.json()).error.details).toHaveProperty('name');
    const session = await login();
    expect(
      (await request('/auth/refresh', 'POST', undefined, session.refresh_token))
        .status,
    ).toBe(200);
    expect(
      (await request('/auth/refresh', 'POST', undefined, session.access_token))
        .status,
    ).toBe(401);
    server.state.users.find((u) => u.id === session.user.id)!.is_active = false;
    expect(
      (await request('/auth/me', 'GET', undefined, session.access_token))
        .status,
    ).toBe(403);
  });
  it('paginates, rejects invalid pagination, and returns contract errors for methods and JSON', async () => {
    const admin = await login('admin@demo.local');
    const list = await (
      await request(
        '/users?page=2&limit=2',
        'GET',
        undefined,
        admin.access_token,
      )
    ).json();
    expect(list.data).toHaveLength(2);
    expect(list.pagination).toEqual({
      total: 4,
      page: 2,
      limit: 2,
      total_pages: 2,
    });
    expect(
      (await request('/users?page=0', 'GET', undefined, admin.access_token))
        .status,
    ).toBe(422);
    const method = await request('/config', 'DELETE');
    expect(method.status).toBe(405);
    expect((await method.json()).error.code).toBe('METHOD_NOT_ALLOWED');
    const malformed = await fetch(base + '/api/v1/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{',
    });
    expect(malformed.status).toBe(400);
  });
  it('supports idempotent alert transitions and blocks backward/final transitions', async () => {
    const { access_token: t } = await login();
    for (const action of ['respond', 'respond'])
      expect(
        (
          await request(
            '/alerts/12/' + action,
            'POST',
            { note: 'On the way' },
            t,
          )
        ).status,
      ).toBe(200);
    expect(
      (await request('/alerts/12/acknowledge', 'POST', {}, t)).status,
    ).toBe(409);
    expect((await request('/alerts/12/resolve', 'POST', {}, t)).status).toBe(
      200,
    );
    expect((await request('/alerts/12/respond', 'POST', {}, t)).status).toBe(
      409,
    );
    expect(
      server.state.events.filter(
        (e) => e.alert_id === 12 && e.type === 'RESPONDING',
      ),
    ).toHaveLength(1);
  });
  it('checks coverage permissions, self-demotion, zone uniqueness and open-alert deletion', async () => {
    const police = await login(),
      admin = await login('admin@demo.local');
    expect(
      (
        await request(
          '/sources',
          'POST',
          { zone_id: 1, name: 'Camera', kind: 'WEBCAM', coverage_area_m2: 20 },
          police.access_token,
        )
      ).status,
    ).toBe(403);
    const created = await request(
      '/sources',
      'POST',
      { zone_id: 1, name: 'Camera', kind: 'WEBCAM' },
      police.access_token,
    );
    expect(created.status).toBe(201);
    expect((await created.json()).data.coverage_area_m2).toBe(40);
    expect(
      (await request('/zones/2', 'DELETE', undefined, admin.access_token))
        .status,
    ).toBe(409);
    expect(
      (
        await request(
          '/users/1',
          'PATCH',
          { is_active: false },
          admin.access_token,
        )
      ).status,
    ).toBe(409);
    expect(
      (
        await request(
          '/zones/1',
          'PATCH',
          { name: 'Stage Area' },
          admin.access_token,
        )
      ).status,
    ).toBe(409);
    expect(
      (
        await request(
          '/zones/1',
          'PATCH',
          { warning_count: 8, critical_count: 3 },
          admin.access_token,
        )
      ).status,
    ).toBe(422);
    const renamed = await request(
      '/zones/1',
      'PATCH',
      { name: 'Festival Gate' },
      admin.access_token,
    );
    expect(renamed.status).toBe(200);
  });
  it('handles reports in RAM, review conflicts, mine filtering and SOS rate limits', async () => {
    const citizen = await login('citizen@demo.local'),
      police = await login();
    const point = server.state.zones[0]!.centroid;
    const form = new FormData();
    form.set(
      'image',
      new Blob([new Uint8Array([255, 216, 255, 217])], { type: 'image/jpeg' }),
      'crowd.jpg',
    );
    form.set('lat', String(point.lat));
    form.set('lng', String(point.lng));
    const response = await fetch(base + '/api/v1/reports/crowd', {
      method: 'POST',
      headers: { Authorization: `Bearer ${citizen.access_token}` },
      body: form,
    });
    expect(response.status).toBe(201);
    const report = (await response.json()).data;
    expect(report.zone_id).toBe(1);
    expect(report).not.toHaveProperty('image');
    expect(
      (
        await request(
          '/reports/' + report.id,
          'PATCH',
          { status: 'VERIFIED' },
          police.access_token,
        )
      ).status,
    ).toBe(200);
    expect(
      (
        await request(
          '/reports/' + report.id,
          'PATCH',
          { status: 'DISMISSED' },
          police.access_token,
        )
      ).status,
    ).toBe(409);
    for (let i = 0; i < 3; i++)
      expect(
        (
          await request(
            '/reports/sos',
            'POST',
            { ...point, sos_type: 'CRUSH_RISK' },
            citizen.access_token,
          )
        ).status,
      ).toBe(201);
    expect(
      (
        await request(
          '/reports/sos',
          'POST',
          { ...point, sos_type: 'CRUSH_RISK' },
          citizen.access_token,
        )
      ).status,
    ).toBe(429);
    expect(
      (
        await (
          await request('/reports/mine', 'GET', undefined, police.access_token)
        ).json()
      ).data,
    ).toEqual([]);
  });
  it('serves remaining admin/config resources and subscription stubs', async () => {
    const admin = await login('admin@demo.local');
    for (const path of [
      '/config',
      '/health',
      '/help-info',
      '/settings',
      '/analytics/summary',
      '/audit-logs',
      '/sources',
      '/zones/1/history',
      '/advisories',
      '/zones/1/public',
    ])
      expect(
        (await request(path, 'GET', undefined, admin.access_token)).status,
        path,
      ).toBe(200);
    expect(
      (
        await request(
          '/analytics/export/alerts.csv',
          'GET',
          undefined,
          admin.access_token,
        )
      ).headers.get('content-type'),
    ).toContain('text/csv');
    expect(
      (
        await request(
          '/settings',
          'PATCH',
          { reraise_after_s: 90 },
          admin.access_token,
        )
      ).status,
    ).toBe(200);
    expect(
      (
        await request(
          '/push/subscriptions',
          'POST',
          {
            endpoint: 'https://push.example.test/a',
            keys: { auth: 'abc', p256dh: 'xyz' },
          },
          admin.access_token,
        )
      ).status,
    ).toBe(201);
    expect(
      (
        await (
          await request('/push/test', 'POST', undefined, admin.access_token)
        ).json()
      ).data.sent,
    ).toBe(0);
  });
});
describe('mock Socket.IO contract', () => {
  it('assigns roles/rooms, separates public events, and emits expiry on request', async () => {
    const police = await login(),
      publicSocket = await connect(),
      privateSocket = await connect(police.access_token);
    expect(publicSocket.hello.role).toBeNull();
    expect(privateSocket.hello.role).toBe('police');
    expect(
      server.io.sockets.sockets
        .get(privateSocket.socket.id!)!
        .rooms.has('role:police'),
    ).toBe(true);
    expect(
      server.io.sockets.sockets
        .get(publicSocket.socket.id!)!
        .rooms.has('role:police'),
    ).toBe(false);
    const publicUpdate = next<{ zone_id: number }>(
        publicSocket.socket,
        'zone:update',
      ),
      privateUpdate = next<ZoneState>(privateSocket.socket, 'zone:detail');
    server.tick();
    expect((await publicUpdate).zone_id).toBe(1);
    expect(await privateUpdate).toHaveProperty('sources');
    const expired = next(privateSocket.socket, 'auth:expired');
    expect(
      (await fetch(base + '/__mock/auth-expired', { method: 'POST' })).status,
    ).toBe(204);
    expect(await expired).toEqual({});
    expect(
      (await request('/auth/me', 'GET', undefined, police.access_token)).status,
    ).toBe(401);
    expect(
      (await request('/auth/refresh', 'POST', undefined, police.refresh_token))
        .status,
    ).toBe(200);
  });
  it('replies only to the frame sender and enforces one streamer per source', async () => {
    const police = await login(),
      a = await connect(police.access_token),
      b = await connect(police.access_token);
    const frame = {
      source_id: 1,
      seq: 1,
      captured_at: new Date().toISOString(),
      width: 640,
      height: 480,
      image: Buffer.from([255, 216, 255, 217]),
      reset: true,
    };
    const first = next<FrameResult>(a.socket, 'frame:result');
    a.socket.emit('frame:submit', frame);
    expect((await first).ok).toBe(true);
    const second = next<FrameResult>(b.socket, 'frame:result');
    b.socket.emit('frame:submit', frame);
    expect((await second).error).toBe('SOURCE_IN_USE');
    const bad = next<FrameResult>(a.socket, 'frame:result');
    a.socket.emit('frame:submit', { ...frame, image: Buffer.from('bad') });
    expect((await bad).error).toBe('BAD_IMAGE');
  });
  it('emits scenario alerts, expiring advisories and SOS without duplicating open alerts', async () => {
    const police = await login(),
      { socket } = await connect(police.access_token),
      time = Date.now();
    server.tick(time);
    server.tick(time + 6000);
    const created = next<Alert>(socket, 'alert:new');
    server.tick(time + 10000);
    expect((await created).level).toBe('WARNING');
    server.tick(time + 16000);
    const escalation = next<{ reason: string }>(socket, 'alert:escalated');
    server.tick(time + 20000);
    expect((await escalation).reason).toBe('LEVEL_UP');
    expect(
      server.state.alerts.filter(
        (a) =>
          a.zone_id === 1 && !['RESOLVED', 'AUTO_CLEARED'].includes(a.status),
      ),
    ).toHaveLength(1);
    expect(
      server.state.reports.some((r) => r.id >= 100 && r.kind === 'SOS'),
    ).toBe(true);
    const retract = next(socket, 'advisory:retracted');
    server.tick(time + 31000);
    expect(await retract).toHaveProperty('id');
    const offline = await fetch(base + '/__mock/scenario?name=offline&zone=1');
    expect(offline.status).toBe(204);
    server.tick();
    expect(server.state.zones[0]!.level).toBe('NO_DATA');
    expect(
      server.state.alerts.find((a) => a.zone_id === 1)!.condition_active,
    ).toBe(true);
  });
});

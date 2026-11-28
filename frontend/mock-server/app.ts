import {
  numericSchema,
  helpSchema,
  thresholdsValid,
  thresholdIssue,
} from '../src/features/admin/settingsSchema';
import express from 'express';
import cors from 'cors';
import { z } from 'zod';
import { createState, now, recordAudit, type MockEmit } from './state';
import { routes, parse, fail, token, paginate } from './http';
import { credentials, registration } from './schemas';
import { resourceRoutes } from './resources';
import { operationRoutes } from './operations';

export function createApp(
  state = createState(),
  emit: MockEmit = () => {},
  password = 'Demo@1234',
) {
  const app = express();
  app.use(cors({ origin: ['http://localhost:5173', 'http://127.0.0.1:5173'] }));
  app.use(express.json({ limit: '1mb' }));
  app.use(
    express.raw({
      type: 'multipart/form-data',
      limit: 5 * 1024 * 1024 + 65536,
    }),
  );
  state.users.forEach((u) => state.passwords.set(u.id, password));
  const { route, finish } = routes(app, state);
  const limits = new Map<string, number[]>();
  const rate = (ip: string, kind: string, max: number, window: number) => {
    const key = `${ip}:${kind}`,
      recent = (limits.get(key) ?? []).filter((t) => Date.now() - t < window);
    if (recent.length >= max)
      fail(429, 'RATE_LIMITED', 'Please try again later.');
    limits.set(key, [...recent, Date.now()]);
  };
  route('post', '/auth/login', 'public', (req, res) => {
    rate(req.ip ?? 'local', 'login', 20, 60000);
    const input = parse(credentials, req.body);
    const user = state.users.find(
      (u) => u.email.toLowerCase() === input.email.toLowerCase(),
    );
    if (!user || state.passwords.get(user.id) !== input.password)
      fail(401, 'UNAUTHENTICATED', 'Invalid email or password.');
    if (!user.is_active) fail(403, 'FORBIDDEN', 'Account is disabled.');
    res.json({
      data: {
        user,
        access_token: token(state, user, 'access'),
        refresh_token: token(state, user, 'refresh'),
        expires_in: 3600,
      },
    });
  });
  route('post', '/auth/register', 'public', (req, res) => {
    rate(req.ip ?? 'local', 'register', 10, 3600000);
    const input = parse(registration, req.body);
    if (
      state.users.some(
        (u) => u.email.toLowerCase() === input.email.toLowerCase(),
      )
    )
      fail(409, 'CONFLICT', 'Email is already registered.');
    const user = {
      id: state.nextId++,
      name: input.name,
      email: input.email,
      role: 'citizen' as const,
      is_active: true,
      created_at: now(),
    };
    state.users.push(user);
    state.passwords.set(user.id, input.password);
    res.status(201).json({
      data: {
        user,
        access_token: token(state, user, 'access'),
        refresh_token: token(state, user, 'refresh'),
        expires_in: 3600,
      },
    });
  });
  route('post', '/auth/refresh', 'refresh', (_req, res, user) =>
    res.json({
      data: { access_token: token(state, user, 'access'), expires_in: 3600 },
    }),
  );
  route('get', '/auth/me', 'citizen', (_req, res, user) =>
    res.json({ data: user }),
  );
  route('get', '/config', 'public', (_req, res) =>
    res.json({ data: state.config }),
  );
  route('get', '/health', 'public', (_req, res) =>
    res.json({
      status: 'ok',
      db: 'ok',
      detector: 'ready',
      worker_alive: true,
      version: state.config.app_version,
    }),
  );
  route('get', '/help-info', 'public', (_req, res) =>
    res.json({ data: state.settings.help_info }),
  );
  route('get', '/settings', 'admin', (_req, res) =>
    res.json({ data: state.settings }),
  );
  route('patch', '/settings', 'admin', (req, res, user) => {
    const schema = numericSchema.extend({ help_info: helpSchema }).partial();
    const next = { ...state.settings, ...parse(schema, req.body) };
    parse(numericSchema.refine(thresholdsValid, thresholdIssue), next);
    state.settings = next;
    for (const key of [
      'target_fps',
      'frame_width',
      'jpeg_quality',
      'stale_after_s',
    ] as const)
      state.config[key] = next[key];
    recordAudit(state, user, 'SETTINGS_UPDATED', 'settings', null);
    res.json({ data: next });
  });
  route('post', '/push/subscriptions', 'police', (req, res, user) => {
    const input = parse(
      z.object({
        endpoint: z.url(),
        keys: z.object({ p256dh: z.string().min(1), auth: z.string().min(1) }),
      }),
      req.body,
    );
    const id = state.subscriptions.get(input.endpoint)?.id ?? state.nextId++;
    state.subscriptions.set(input.endpoint, { id, userId: user.id });
    res.status(201).json({ data: { id } });
  });
  route('delete', '/push/subscriptions', 'police', (req, res, user) => {
    const endpoint = parse(z.string().min(1), req.query.endpoint);
    if (state.subscriptions.get(endpoint)?.userId === user.id)
      state.subscriptions.delete(endpoint);
    res.sendStatus(204);
  });
  route('post', '/push/test', 'police', (_req, res) =>
    res.json({ data: { sent: 0 } }),
  );
  route('get', '/analytics/summary', 'police', (req, res) => {
    const input = parse(
      z.object({
        from: z.iso.datetime().optional(),
        to: z.iso.datetime().optional(),
      }),
      req.query,
    );
    const to = input.to ?? now(),
      from = input.from ?? new Date(Date.parse(to) - 86400000).toISOString();
    if (from > to) fail(422, 'VALIDATION_ERROR', 'From must precede to.');
    const alerts = state.alerts.filter(
      (a) => a.created_at >= from && a.created_at <= to,
    );
    const average = (values: number[]) =>
      values.length
        ? values.reduce((sum, v) => sum + v, 0) / values.length
        : null;
    const buckets = new Map<
      string,
      { zone_id: number; zone_name: string; hour: number; values: number[] }
    >();
    for (const a of alerts) {
      const hour = new Date(Date.parse(a.created_at) + 19800000).getUTCHours(),
        key = `${a.zone_id}:${hour}`;
      const b = buckets.get(key) ?? {
        zone_id: a.zone_id,
        zone_name: a.zone_name,
        hour,
        values: [],
      };
      b.values.push(a.peak_density);
      buckets.set(key, b);
    }
    const peaks = new Map<
      number,
      { zone_id: number; zone_name: string; hour: number; avg_density: number }
    >();
    for (const { values, ...bucket } of buckets.values()) {
      const density = average(values)!;
      const peak = peaks.get(bucket.zone_id);
      if (
        !peak ||
        density > peak.avg_density ||
        (density === peak.avg_density && bucket.hour < peak.hour)
      )
        peaks.set(bucket.zone_id, { ...bucket, avg_density: density });
    }
    res.json({
      data: {
        from,
        to,
        timezone: 'Asia/Kolkata',
        alerts_by_zone: state.zones.map((z) => ({
          zone_id: z.id,
          zone_name: z.name,
          warning: alerts.filter(
            (a) => a.zone_id === z.id && a.peak_level === 'WARNING',
          ).length,
          critical: alerts.filter(
            (a) => a.zone_id === z.id && a.peak_level === 'CRITICAL',
          ).length,
        })),
        avg_ack_seconds: average(
          alerts.flatMap((a) =>
            a.acknowledged_at
              ? [
                  (Date.parse(a.acknowledged_at) - Date.parse(a.created_at)) /
                    1000,
                ]
              : [],
          ),
        ),
        avg_resolve_seconds: average(
          alerts.flatMap((a) =>
            a.resolved_at
              ? [(Date.parse(a.resolved_at) - Date.parse(a.created_at)) / 1000]
              : [],
          ),
        ),
        peak_hours: [...peaks.values()],
        reports_by_status: Object.fromEntries(
          ['PENDING', 'VERIFIED', 'DISMISSED'].map((status) => [
            status,
            state.reports.filter(
              (r) =>
                r.status === status &&
                r.created_at >= from &&
                r.created_at <= to,
            ).length,
          ]),
        ),
      },
    });
  });
  route('get', '/analytics/export/alerts.csv', 'admin', (req, res) => {
    const escape = (value: unknown) =>
      `"${String(value ?? '').replaceAll('"', '""')}"`;
    const rows = state.alerts
      .filter(
        (a) =>
          (!req.query.from || a.created_at >= String(req.query.from)) &&
          (!req.query.to || a.created_at <= String(req.query.to)),
      )
      .map((a) =>
        [
          a.id,
          a.zone_name,
          a.level,
          a.peak_level,
          a.status,
          a.peak_density,
          a.peak_count,
          a.created_at,
          a.acknowledged_at,
          a.resolved_at,
        ]
          .map(escape)
          .join(','),
      );
    res
      .type('text/csv')
      .attachment('alerts.csv')
      .send(
        [
          'id,zone,level,peak_level,status,peak_density,peak_count,created_at,acknowledged_at,resolved_at',
          ...rows,
        ].join('\r\n'),
      );
  });
  route('get', '/audit-logs', 'admin', (req, res) =>
    res.json(
      paginate(
        state.audit.filter(
          (a) =>
            (!req.query.action || a.action === req.query.action) &&
            (!req.query.actor_id || a.actor?.id === Number(req.query.actor_id)),
        ),
        req.query,
      ),
    ),
  );
  resourceRoutes(route, state, emit);
  operationRoutes(route, state, emit);
  return { app, state, finish };
}

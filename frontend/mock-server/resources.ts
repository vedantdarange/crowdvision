import { z } from 'zod';
import type { ZoneState, SourceInfo } from '../../contract/types';
import {
  now,
  publicZone,
  recordAudit,
  type MockEmit,
  type MockState,
} from './state';
import { fail, paginate, parse, type routes } from './http';
import { registration, zoneInput } from './schemas';
type Route = ReturnType<typeof routes>['route'];

export function resourceRoutes(route: Route, state: MockState, emit: MockEmit) {
  const zone = (id: unknown) =>
    state.zones.find((z) => z.id === Number(id)) ??
    fail(404, 'NOT_FOUND', 'Zone not found.');
  const source = (id: unknown) =>
    state.zones.flatMap((z) => z.sources).find((s) => s.id === Number(id)) ??
    fail(404, 'NOT_FOUND', 'Source not found.');
  route('get', '/users', 'admin', (req, res) =>
    res.json(
      paginate(
        state.users.filter(
          (u) =>
            (!req.query.role || u.role === req.query.role) &&
            (!req.query.is_active ||
              u.is_active === (req.query.is_active === 'true')) &&
            (!req.query.q ||
              `${u.name} ${u.email}`
                .toLowerCase()
                .includes(String(req.query.q).toLowerCase())),
        ),
        req.query,
      ),
    ),
  );
  route('post', '/users', 'admin', (req, res, user) => {
    const input = parse(
      registration.extend({ role: z.enum(['police', 'admin']) }),
      req.body,
    );
    if (
      state.users.some(
        (u) => u.email.toLowerCase() === input.email.toLowerCase(),
      )
    )
      fail(409, 'CONFLICT', 'Email is already registered.');
    const created = {
      id: state.nextId++,
      name: input.name,
      email: input.email,
      role: input.role,
      is_active: true,
      created_at: now(),
    };
    state.users.push(created);
    state.passwords.set(created.id, input.password);
    recordAudit(state, user, 'USER_CREATED', 'user', created.id);
    res.status(201).json({ data: created });
  });
  route('patch', '/users/:id', 'admin', (req, res, user) => {
    const input = parse(
      z.object({
        name: z.string().trim().min(1).optional(),
        role: z.enum(['citizen', 'police', 'admin']).optional(),
        is_active: z.boolean().optional(),
        password: z.string().min(8).optional(),
      }),
      req.body,
    );
    const target =
      state.users.find((u) => u.id === Number(req.params.id)) ??
      fail(404, 'NOT_FOUND', 'User not found.');
    if (
      target.id === user.id &&
      (input.is_active === false || (input.role && input.role !== 'admin'))
    )
      fail(409, 'CONFLICT', 'You cannot disable or demote yourself.');
    const { password, ...fields } = input;
    Object.assign(target, fields);
    if (password) state.passwords.set(target.id, password);
    recordAudit(state, user, 'USER_UPDATED', 'user', target.id);
    res.json({ data: target });
  });
  route('get', '/zones/live', 'public', (_req, res) =>
    res.json({ data: state.zones.filter((z) => z.is_active).map(publicZone) }),
  );
  route('get', '/zones/:id/public', 'public', (req, res) => {
    const selected = zone(req.params.id);
    if (!selected.is_active) fail(404, 'NOT_FOUND', 'Zone not found.');
    const distance = (z: ZoneState) =>
      Math.hypot(
        z.centroid.lat - selected.centroid.lat,
        (z.centroid.lng - selected.centroid.lng) *
          Math.cos((selected.centroid.lat * Math.PI) / 180),
      );
    res.json({
      data: {
        state: publicZone(selected),
        alternatives: state.zones
          .filter(
            (z) => z.id !== selected.id && z.is_active && z.level === 'SAFE',
          )
          .sort((a, b) => distance(a) - distance(b))
          .slice(0, 3)
          .map(publicZone),
      },
    });
  });
  route('get', '/zones', 'police', (req, res, user) => {
    if (req.query.include_inactive === 'true' && user.role !== 'admin')
      fail(403, 'FORBIDDEN', 'Only admins can include inactive zones.');
    res.json({
      data: state.zones.filter(
        (z) => z.is_active || req.query.include_inactive === 'true',
      ),
    });
  });
  route('get', '/zones/:id', 'police', (req, res) =>
    res.json({ data: zone(req.params.id) }),
  );
  function validateZone(next: ZoneState) {
    if (
      state.zones.some(
        (z) =>
          z.id !== next.id &&
          z.is_active &&
          next.is_active &&
          z.name.toLowerCase() === next.name.toLowerCase(),
      )
    )
      fail(409, 'CONFLICT', 'An active zone already has this name.');
    parse(
      z
        .object({ warning_density: z.number(), critical_density: z.number() })
        .refine((x) => x.warning_density < x.critical_density, {
          path: ['warning_density'],
          message: 'Warning must be below critical.',
        }),
      next,
    );
    if (next.mode === 'COUNT')
      parse(
        z
          .object({
            warning_count: z.number().positive(),
            critical_count: z.number().positive(),
          })
          .refine((x) => x.warning_count < x.critical_count, {
            path: ['warning_count'],
            message: 'Warning must be below critical.',
          }),
        next,
      );
    const ring = next.geometry.coordinates[0]!;
    const lat =
      ring.slice(0, -1).reduce((sum, p) => sum + p[1]!, 0) / (ring.length - 1);
    const lng =
      ring.slice(0, -1).reduce((sum, p) => sum + p[0]!, 0) / (ring.length - 1);
    const scale = 111195,
      cos = Math.cos((lat * Math.PI) / 180);
    const area = Math.abs(
      next.geometry.coordinates.reduce((total, r, index) => {
        let sum = 0;
        for (let i = 0; i < r.length - 1; i++) {
          const a = r[i]!,
            b = r[i + 1]!;
          sum += (a[0]! - lng) * (b[1]! - lat) - (b[0]! - lng) * (a[1]! - lat);
        }
        return (
          total +
          (index === 0 ? 1 : -1) * Math.abs((sum * scale * scale * cos) / 2)
        );
      }, 0),
    );
    parse(
      z
        .number()
        .min(1)
        .max(10_000_000)
        .refine(
          (a) => Math.abs(next.area_m2 - a) / a <= 0.1,
          'Area differs from polygon by more than 10%.',
        ),
      area,
    );
    next.area_m2 = area;
    next.centroid = { lat, lng };
  }
  route('post', '/zones', 'admin', (req, res, user) => {
    const input = parse(zoneInput, req.body);
    const next: ZoneState = {
      id: state.nextId++,
      description: '',
      centroid: { lat: 0, lng: 0 },
      mode: 'DENSITY',
      warning_density: state.settings.default_warning_density,
      critical_density: state.settings.default_critical_density,
      warning_count: null,
      critical_count: null,
      is_active: true,
      created_at: now(),
      updated_at: now(),
      level: 'NO_DATA',
      trend: 'STEADY',
      count: null,
      density: null,
      sources: [],
      open_alert_id: null,
      live_updated_at: null,
      ...input,
    };
    validateZone(next);
    state.zones.push(next);
    recordAudit(state, user, 'ZONE_CREATED', 'zone', next.id);
    res.status(201).json({ data: next });
  });
  route('patch', '/zones/:id', 'admin', (req, res, user) => {
    const input = parse(
        zoneInput.partial().extend({ is_active: z.boolean().optional() }),
        req.body,
      ),
      target = zone(req.params.id);
    if (input.is_active === false && target.open_alert_id !== null)
      fail(409, 'CONFLICT', 'Resolve the open alert first.');
    const next = { ...target, ...input, updated_at: now() };
    validateZone(next);
    Object.assign(target, next);
    recordAudit(state, user, 'ZONE_UPDATED', 'zone', target.id);
    res.json({ data: target });
  });
  route('delete', '/zones/:id', 'admin', (req, res, user) => {
    const target = zone(req.params.id);
    if (target.open_alert_id !== null)
      fail(409, 'CONFLICT', 'Resolve the open alert first.');
    target.is_active = false;
    recordAudit(state, user, 'ZONE_DELETED', 'zone', target.id);
    res.sendStatus(204);
  });
  route('get', '/zones/:id/history', 'police', (req, res) => {
    const target = zone(req.params.id);
    const input = parse(
      z.object({
        bucket_s: z.coerce
          .number()
          .refine((n) => [10, 60, 300].includes(n))
          .default(10),
        from: z.iso.datetime().optional(),
        to: z.iso.datetime().optional(),
      }),
      req.query,
    );
    const end = Date.parse(input.to ?? now()),
      start = Date.parse(input.from ?? new Date(end - 1800000).toISOString());
    if (start > end) fail(422, 'VALIDATION_ERROR', 'From must precede to.');
    const data =
      target.count === null
        ? []
        : Array.from(
            {
              length: Math.min(
                5000,
                Math.floor((end - start) / 1000 / input.bucket_s) + 1,
              ),
            },
            (_, i) => ({
              ts: new Date(start + i * input.bucket_s * 1000).toISOString(),
              count: target.count!,
              density: target.density!,
              level: target.level,
            }),
          );
    res.json({ data });
  });
  route('get', '/sources', 'police', (req, res) =>
    res.json({
      data: state.zones
        .flatMap((z) => z.sources)
        .filter(
          (s) => !req.query.zone_id || s.zone_id === Number(req.query.zone_id),
        ),
    }),
  );
  route('post', '/sources', 'police', (req, res, user) => {
    const input = parse(
      z.object({
        zone_id: z.number().int(),
        name: z.string().trim().min(1),
        kind: z.enum(['WEBCAM', 'VIDEO_FILE']),
        coverage_area_m2: z.number().optional(),
      }),
      req.body,
    );
    if (input.coverage_area_m2 !== undefined && user.role !== 'admin')
      fail(403, 'FORBIDDEN', 'Only admins can set coverage area.');
    const target = zone(input.zone_id);
    const coverage = parse(
      z
        .number()
        .min(1)
        .max(target.area_m2 * 2),
      input.coverage_area_m2 ?? target.area_m2,
    );
    const created: SourceInfo = {
      ...input,
      id: state.nextId++,
      coverage_area_m2: coverage,
      is_active: true,
      status: 'OFFLINE',
      last_frame_at: null,
      created_at: now(),
    };
    target.sources.push(created);
    recordAudit(state, user, 'SOURCE_CREATED', 'source', created.id);
    res.status(201).json({ data: created });
  });
  route('patch', '/sources/:id', 'admin', (req, res, user) => {
    const target = source(req.params.id);
    const input = parse(
      z.object({
        name: z.string().trim().min(1).optional(),
        coverage_area_m2: z
          .number()
          .min(1)
          .max(zone(target.zone_id).area_m2 * 2)
          .optional(),
        is_active: z.boolean().optional(),
      }),
      req.body,
    );
    Object.assign(target, input);
    if (!target.is_active) target.status = 'OFFLINE';
    recordAudit(state, user, 'SOURCE_UPDATED', 'source', target.id);
    emit(
      'source:status',
      {
        source_id: target.id,
        zone_id: target.zone_id,
        status: target.status,
        last_frame_at: target.last_frame_at,
      },
      'role:police',
    );
    res.json({ data: target });
  });
  route('delete', '/sources/:id', 'admin', (req, res, user) => {
    const target = source(req.params.id);
    target.is_active = false;
    target.status = 'OFFLINE';
    recordAudit(state, user, 'SOURCE_DELETED', 'source', target.id);
    res.sendStatus(204);
  });
}

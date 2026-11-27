import { z } from 'zod';
import type { AlertStatus, Report } from '../../contract/types';
import {
  now,
  recordAudit,
  fixture,
  type MockState,
  type MockEmit,
} from './state';
import { parse, fail, paginate, type routes } from './http';
import { advisoryInput, note, point } from './schemas';
type Route = ReturnType<typeof routes>['route'];
export function operationRoutes(
  route: Route,
  state: MockState,
  emit: MockEmit,
) {
  const zoneName = (id: number | null | undefined) =>
    id == null
      ? null
      : (
          state.zones.find((z) => z.id === id) ??
          fail(404, 'NOT_FOUND', 'Zone not found.')
        ).name;
  route('get', '/alerts', 'police', (req, res) => {
    const rows = state.alerts
      .filter(
        (a) =>
          (!req.query.status ||
            String(req.query.status).split(',').includes(a.status)) &&
          (!req.query.level || a.level === req.query.level) &&
          (!req.query.zone_id || a.zone_id === Number(req.query.zone_id)) &&
          (req.query.active !== 'true' ||
            !['RESOLVED', 'AUTO_CLEARED'].includes(a.status)) &&
          (!req.query.from || a.created_at >= String(req.query.from)) &&
          (!req.query.to || a.created_at <= String(req.query.to)),
      )
      .sort((a, b) =>
        req.query.sort === 'created_at'
          ? a.created_at.localeCompare(b.created_at)
          : b.created_at.localeCompare(a.created_at),
      );
    res.json(paginate(rows, req.query));
  });
  route('get', '/alerts/:id', 'police', (req, res) => {
    const alert =
      state.alerts.find((a) => a.id === Number(req.params.id)) ??
      fail(404, 'NOT_FOUND', 'Alert not found.');
    res.json({
      data: {
        ...alert,
        events: state.events.filter((e) => e.alert_id === alert.id),
      },
    });
  });
  for (const action of ['acknowledge', 'respond', 'resolve'] as const)
    route('post', `/alerts/:id/${action}`, 'police', (req, res, user) => {
      const input = parse(note, req.body ?? {}),
        alert =
          state.alerts.find((a) => a.id === Number(req.params.id)) ??
          fail(404, 'NOT_FOUND', 'Alert not found.');
      const status: AlertStatus =
        action === 'acknowledge'
          ? 'ACKNOWLEDGED'
          : action === 'respond'
            ? 'RESPONDING'
            : 'RESOLVED';
      if (alert.status === status) {
        res.json({ data: alert });
        return;
      }
      if (
        ['RESOLVED', 'AUTO_CLEARED'].includes(alert.status) ||
        (status === 'ACKNOWLEDGED' && alert.status !== 'NEW')
      )
        fail(409, 'INVALID_TRANSITION', 'Someone already updated this alert.');
      alert.status = status;
      const actor = { id: user.id, name: user.name };
      if (action === 'acknowledge') {
        alert.acknowledged_at = now();
        alert.acknowledged_by = actor;
      }
      if (action === 'respond') {
        alert.responding_at = now();
        alert.responding_by = actor;
      }
      if (action === 'resolve') {
        alert.resolved_at = now();
        alert.resolved_by = actor;
        alert.resolution_note = input.note ?? null;
        const zone = state.zones.find((z) => z.id === alert.zone_id);
        if (zone) zone.open_alert_id = null;
      }
      state.events.push({
        id: state.nextId++,
        alert_id: alert.id,
        type: status,
        actor,
        data: input.note ? { note: input.note } : {},
        created_at: now(),
      });
      recordAudit(state, user, `ALERT_${status}`, 'alert', alert.id);
      emit('alert:updated', alert, 'role:police');
      res.json({ data: alert });
    });
  route('get', '/advisories', 'public', (req, res) =>
    res.json({
      data: state.advisories
        .filter(
          (a) =>
            a.is_active &&
            (!a.expires_at || Date.parse(a.expires_at) > Date.now()) &&
            (!req.query.zone_id ||
              a.zone_id === null ||
              a.zone_id === Number(req.query.zone_id)),
        )
        .sort((a, b) => b.created_at.localeCompare(a.created_at)),
    }),
  );
  route('post', '/advisories', 'police', (req, res, user) => {
    const input = parse(advisoryInput, req.body),
      created = {
        ...input,
        id: state.nextId++,
        zone_id: input.zone_id ?? null,
        zone_name: zoneName(input.zone_id),
        expires_at: input.expires_at ?? null,
        created_by: { id: user.id, name: user.name },
        created_at: now(),
        is_active: true,
      };
    state.advisories.push(created);
    recordAudit(state, user, 'ADVISORY_CREATED', 'advisory', created.id);
    emit('advisory:new', created, 'public');
    res.status(201).json({ data: created });
  });
  route('delete', '/advisories/:id', 'police', (req, res, user) => {
    const a =
      state.advisories.find((a) => a.id === Number(req.params.id)) ??
      fail(404, 'NOT_FOUND', 'Advisory not found.');
    a.is_active = false;
    recordAudit(state, user, 'ADVISORY_RETRACTED', 'advisory', a.id);
    emit('advisory:retracted', { id: a.id }, 'public');
    res.sendStatus(204);
  });
  function matchedZone(lat: number, lng: number) {
    return state.zones.find(
      (z) =>
        z.is_active &&
        z.geometry.coordinates.every((ring, ringIndex) => {
          let inside = false;
          for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
            const a = ring[i]!,
              b = ring[j]!;
            if (
              a[1]! > lat !== b[1]! > lat &&
              lng < ((b[0]! - a[0]!) * (lat - a[1]!)) / (b[1]! - a[1]!) + a[0]!
            )
              inside = !inside;
          }
          return ringIndex === 0 ? inside : !inside;
        }),
    );
  }
  const reportLimits = new Map<string, number[]>();
  function rateReport(userId: number, kind: string) {
    const key = `${userId}:${kind}`,
      window = kind === 'CROWD' ? 60000 : 600000,
      max = kind === 'CROWD' ? 1 : 3;
    const recent = (reportLimits.get(key) ?? []).filter(
      (t) => Date.now() - t < window,
    );
    if (recent.length >= max)
      fail(429, 'RATE_LIMITED', 'Please wait before sending another report.');
    reportLimits.set(key, [...recent, Date.now()]);
  }
  route('post', '/reports/sos', 'citizen', (req, res, user) => {
    const input = parse(
      z.object({
        ...point,
        sos_type: z.enum([
          'MEDICAL',
          'CRUSH_RISK',
          'FIRE',
          'LOST_CHILD',
          'OTHER',
        ]),
        note: z.string().optional(),
      }),
      req.body,
    );
    rateReport(user.id, 'SOS');
    const zone = matchedZone(input.lat, input.lng);
    const report: Report = {
      ...input,
      id: state.nextId++,
      kind: 'SOS',
      status: 'PENDING',
      zone_id: zone?.id ?? null,
      zone_name: zone?.name ?? null,
      count: null,
      density_hint: null,
      note: input.note ?? null,
      created_by: { id: user.id, name: user.name },
      created_at: now(),
      reviewed_by: null,
      reviewed_at: null,
      review_note: null,
    };
    state.reports.push(report);
    emit('report:new', report, 'role:police');
    res.status(201).json({ data: report });
  });
  route('post', '/reports/crowd', 'citizen', async (req, res, user) => {
    // Native multipart parsing stays in RAM; no disk-spooling middleware.
    if (!Buffer.isBuffer(req.body))
      fail(422, 'VALIDATION_ERROR', 'Use multipart/form-data.');
    let form: FormData;
    try {
      form = await new Request('http://localhost/upload', {
        method: 'POST',
        headers: { 'Content-Type': req.get('content-type') ?? '' },
        body: new Uint8Array(req.body),
      }).formData();
    } catch {
      fail(400, 'BAD_REQUEST', 'Malformed multipart body.');
    }
    const input = parse(z.object({ ...point, note: z.string().optional() }), {
      lat: form.get('lat') ?? undefined,
      lng: form.get('lng') ?? undefined,
      note: form.get('note') ?? undefined,
    });
    const image = form.get('image');
    if (
      !(image instanceof File) ||
      !['image/jpeg', 'image/png'].includes(image.type)
    )
      fail(422, 'VALIDATION_ERROR', 'Select a JPEG or PNG image.');
    if (image.size > 5 * 1024 * 1024)
      fail(413, 'PAYLOAD_TOO_LARGE', 'Image exceeds 5 MB.');
    rateReport(user.id, 'CROWD');
    const zone = matchedZone(input.lat, input.lng),
      count = 14;
    const report: Report = {
      ...fixture<Report>('report_crowd'),
      ...input,
      id: state.nextId++,
      zone_id: zone?.id ?? null,
      zone_name: zone?.name ?? null,
      count,
      density_hint: zone ? count / zone.area_m2 : null,
      note: input.note ?? null,
      created_by: { id: user.id, name: user.name },
      created_at: now(),
    };
    state.reports.push(report);
    emit('report:new', report, 'role:police');
    res.status(201).json({ data: report });
  });
  route('get', '/reports/mine', 'citizen', (req, res, user) =>
    res.json(
      paginate(
        state.reports.filter((r) => r.created_by.id === user.id),
        req.query,
      ),
    ),
  );
  route('get', '/reports', 'police', (req, res) =>
    res.json(
      paginate(
        state.reports.filter(
          (r) =>
            (!req.query.kind || r.kind === req.query.kind) &&
            (!req.query.status || r.status === req.query.status) &&
            (!req.query.zone_id || r.zone_id === Number(req.query.zone_id)),
        ),
        req.query,
      ),
    ),
  );
  route('patch', '/reports/:id', 'police', (req, res, user) => {
    const input = parse(
        z.object({
          status: z.enum(['VERIFIED', 'DISMISSED']),
          review_note: z.string().optional(),
        }),
        req.body,
      ),
      report =
        state.reports.find((r) => r.id === Number(req.params.id)) ??
        fail(404, 'NOT_FOUND', 'Report not found.');
    if (report.status !== 'PENDING')
      fail(409, 'INVALID_TRANSITION', 'Report was already reviewed.');
    Object.assign(report, {
      ...input,
      review_note: input.review_note ?? null,
      reviewed_at: now(),
      reviewed_by: { id: user.id, name: user.name },
    });
    recordAudit(state, user, 'REPORT_REVIEWED', 'report', report.id);
    emit('report:updated', report, [
      'role:police',
      `user:${report.created_by.id}`,
    ]);
    res.json({ data: report });
  });
}

import { createServer } from 'node:http';
import { Server } from 'socket.io';
import { z } from 'zod';
import type {
  Advisory,
  FrameResult,
  FrameSubmit,
  Report,
} from '../../contract/types';
import { createApp } from './app';
import { createState, fixture, now, type MockEmit } from './state';
import { authenticate, fail, parse } from './http';
import { createEngine } from './engine';

export function createMockServer({
  password = 'Demo@1234',
  timers = true,
}: { password?: string; timers?: boolean } = {}) {
  const state = createState();
  const emit: MockEmit = (event, payload, room) => {
    if (room) io.to(room).emit(event, payload);
    else io.emit(event, payload);
  };
  const { app, finish } = createApp(state, emit, password);
  const http = createServer(app);
  const io = new Server(http, {
    cors: { origin: ['http://localhost:5173', 'http://127.0.0.1:5173'] },
    maxHttpBufferSize: 5 * 1024 * 1024,
  });
  const engine = createEngine(state, emit);
  const leases = new Map<number, { socket: string; expires: number }>();
  const buffers = new Map<number, number[]>();
  let scenario: 'ramp' | 'spike' | 'flap' | 'offline' = 'ramp',
    scenarioZone = 1,
    started = Date.now(),
    lastBroadcast = Date.now();
  const expire = (
    socket: typeof io.sockets.sockets extends Map<string, infer S> ? S : never,
  ) => {
    for (const room of socket.rooms)
      if (room !== 'public' && room !== socket.id) void socket.leave(room);
    socket.emit('auth:expired', {});
    socket.disconnect(true);
  };
  io.on('connection', (socket) => {
    const supplied = socket.handshake.auth.token as string | undefined,
      user = authenticate(state, supplied);
    void socket.join('public');
    if (user?.is_active) {
      socket.data.userId = user.id;
      socket.data.role = user.role;
      void socket.join(`user:${user.id}`);
      if (user.role !== 'citizen') void socket.join('role:police');
      if (user.role === 'admin') void socket.join('role:admin');
    } else if (supplied) socket.emit('auth:expired', {});
    socket.emit('hello', {
      role: user?.is_active ? user.role : null,
      server_time: now(),
      contract_version: '1.1.0',
    });
    socket.on(
      'frame:submit',
      (frame: Omit<FrameSubmit, 'image'> & { image: unknown }) => {
        const result: FrameResult = {
          source_id: frame?.source_id ?? 0,
          seq: frame?.seq ?? 0,
          ok: false,
          count: 0,
          boxes: [],
          infer_ms: 0,
          smoothed_count: null,
          density: null,
          level: null,
        };
        const current = authenticate(state, supplied);
        if (
          !current?.is_active ||
          current.role === 'citizen' ||
          current.role !== socket.data.role
        ) {
          result.error = 'FORBIDDEN';
          socket.emit('frame:result', result);
          if (socket.data.userId) expire(socket);
          return;
        }
        const zone = state.zones.find(
          (z) =>
            z.is_active &&
            z.sources.some((s) => s.id === frame.source_id && s.is_active),
        );
        const source = zone?.sources.find((s) => s.id === frame.source_id);
        if (!zone || !source) result.error = 'UNKNOWN_SOURCE';
        else if (
          !Buffer.isBuffer(frame.image) ||
          frame.image.length < 3 ||
          frame.image[0] !== 255 ||
          frame.image[1] !== 216 ||
          frame.image[2] !== 255 ||
          !Number.isInteger(frame.seq) ||
          frame.seq < 1 ||
          !(frame.width > 0 && frame.height > 0) ||
          !Number.isFinite(Date.parse(frame.captured_at))
        )
          result.error = 'BAD_IMAGE';
        else {
          const lease = leases.get(source.id);
          if (lease && lease.socket !== socket.id && lease.expires > Date.now())
            result.error = 'SOURCE_IN_USE';
          else {
            leases.set(source.id, {
              socket: socket.id,
              expires: Date.now() + state.settings.stale_after_s * 1000,
            });
            if (frame.reset) buffers.delete(source.id);
            const count = 2 + (frame.seq % 5),
              buffer = [...(buffers.get(source.id) ?? []), count].slice(
                -state.settings.smoothing_window,
              );
            buffers.set(source.id, buffer);
            const sorted = [...buffer].sort((a, b) => a - b),
              mid = Math.floor(sorted.length / 2),
              smoothed =
                sorted.length % 2
                  ? sorted[mid]!
                  : (sorted[mid - 1]! + sorted[mid]!) / 2;
            const old = source.status;
            source.status = 'ONLINE';
            source.last_frame_at = now();
            if (old !== 'ONLINE')
              emit(
                'source:status',
                {
                  source_id: source.id,
                  zone_id: zone.id,
                  status: 'ONLINE',
                  last_frame_at: source.last_frame_at,
                },
                'role:police',
              );
            const online = zone.sources.filter((s) => s.status === 'ONLINE');
            const value = (id: number) => {
              const values = [...(buffers.get(id) ?? [smoothed])].sort(
                  (a, b) => a - b,
                ),
                m = Math.floor(values.length / 2);
              return values.length % 2
                ? values[m]!
                : (values[m - 1]! + values[m]!) / 2;
            };
            engine.apply(
              zone,
              Math.max(...online.map((s) => value(s.id))),
              Math.max(...online.map((s) => value(s.id) / s.coverage_area_m2)),
            );
            Object.assign(result, {
              ok: true,
              count,
              boxes: Array.from({ length: count }, (_, i) => {
                const x = (i % 4) * 0.22;
                return [x, 0.1, x + 0.15, 0.9, 0.9];
              }),
              infer_ms: 45,
              smoothed_count: zone.count,
              density: zone.density,
              level: zone.level,
            });
          }
        }
        socket.emit('frame:result', result);
      },
    );
    socket.on('disconnect', () => {
      for (const [id, lease] of leases)
        if (lease.socket === socket.id) leases.delete(id);
    });
  });
  app.get('/__mock/scenario', (req, res, next) => {
    try {
      const input = parse(
        z.object({
          name: z.enum(['spike', 'flap', 'offline']),
          zone: z.coerce.number().int().positive().default(1),
        }),
        req.query,
      );
      if (!state.zones.some((z) => z.id === input.zone))
        fail(404, 'NOT_FOUND', 'Zone not found.');
      scenario = input.name;
      scenarioZone = input.zone;
      started = Date.now();
      res.sendStatus(204);
    } catch (error) {
      next(error);
    }
  });
  // Explicitly approved F0-only control; not part of /api/v1 or the production contract.
  app.post('/__mock/auth-expired', (_req, res) => {
    for (const session of state.tokens.values())
      if (session.kind === 'access') session.expires = 0;
    for (const socket of io.sockets.sockets.values())
      if (socket.data.userId) expire(socket);
    res.sendStatus(204);
  });
  finish();
  function tick(time = Date.now()) {
    for (const socket of io.sockets.sockets.values())
      if (socket.data.userId) {
        const u = authenticate(state, socket.handshake.auth.token as string);
        if (!u?.is_active || u.role !== socket.data.role) expire(socket);
      }
    for (const z of state.zones)
      for (const s of z.sources)
        if (
          s.status === 'ONLINE' &&
          time - Date.parse(s.last_frame_at ?? '') >
            state.settings.stale_after_s * 1000
        ) {
          s.status = 'OFFLINE';
          emit(
            'source:status',
            {
              source_id: s.id,
              zone_id: z.id,
              status: s.status,
              last_frame_at: s.last_frame_at,
            },
            'role:police',
          );
          if (
            z.id !== scenarioZone &&
            z.sources.every((s) => s.status === 'OFFLINE')
          )
            engine.apply(z, null, null, time);
        }
    const zone = state.zones.find((z) => z.id === scenarioZone && z.is_active);
    if (
      zone &&
      !zone.sources.some((s) => (leases.get(s.id)?.expires ?? 0) > time)
    ) {
      const seconds = Math.floor((time - started) / 1000) % 44;
      const count =
        scenario === 'offline'
          ? null
          : scenario === 'spike'
            ? seconds === 8
              ? 6
              : 2
            : scenario === 'flap'
              ? seconds % 2
                ? 4
                : 2
              : seconds < 5
                ? 2
                : seconds < 15
                  ? 4
                  : seconds < 28
                    ? 6
                    : 1;
      if (zone.sources[0]) {
        const s = zone.sources[0],
          old = s.status;
        s.status = count === null ? 'OFFLINE' : 'ONLINE';
        s.last_frame_at = count === null ? s.last_frame_at : now();
        if (s.status !== old)
          emit(
            'source:status',
            {
              source_id: s.id,
              zone_id: zone.id,
              status: s.status,
              last_frame_at: s.last_frame_at,
            },
            'role:police',
          );
      }
      engine.apply(
        zone,
        count,
        count === null
          ? null
          : count / (zone.sources[0]?.coverage_area_m2 ?? zone.area_m2),
        time,
      );
    }
    for (const a of state.advisories)
      if (a.is_active && a.expires_at && Date.parse(a.expires_at) <= time) {
        a.is_active = false;
        emit('advisory:retracted', { id: a.id }, 'public');
      }
    if (time - lastBroadcast >= 20000) {
      lastBroadcast = time;
      const advisory = {
        ...fixture<Advisory>('advisory'),
        id: state.nextId++,
        created_at: now(),
        expires_at: new Date(time + 10000).toISOString(),
      };
      state.advisories.push(advisory);
      emit('advisory:new', advisory, 'public');
      const report = {
        ...fixture<Report>(
          Math.floor((time - started) / 20000) % 2
            ? 'report_sos'
            : 'report_crowd',
        ),
        id: state.nextId++,
        created_at: now(),
      };
      state.reports.push(report);
      emit('report:new', report, 'role:police');
    }
  }
  const interval = timers ? setInterval(tick, 1000) : undefined;
  return {
    app,
    http,
    io,
    state,
    tick,
    engine,
    close: async () => {
      if (interval) clearInterval(interval);
      await new Promise<void>((resolve) => io.close(() => resolve()));
    },
  };
}

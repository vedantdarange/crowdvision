import type { Request, Response, NextFunction, Express } from 'express';
import { z } from 'zod';
import { randomUUID } from 'node:crypto';
import type { ApiList, ErrorCode, User } from '../../contract/types';
import type { MockState } from './state';

export class HttpError extends Error {
  constructor(
    public status: number,
    public code: ErrorCode,
    message: string,
    public details?: Record<string, string[]>,
  ) {
    super(message);
  }
}
export function fail(status: number, code: ErrorCode, message: string): never {
  throw new HttpError(status, code, message);
}
export function parse<T>(schema: z.ZodType<T>, input: unknown): T {
  const result = schema.safeParse(input);
  if (!result.success) {
    const details: Record<string, string[]> = {};
    for (const issue of result.error.issues)
      (details[issue.path.join('.') || 'body'] ??= []).push(issue.message);
    throw new HttpError(
      422,
      'VALIDATION_ERROR',
      'Check the highlighted fields.',
      details,
    );
  }
  return result.data;
}
export function token(
  state: MockState,
  user: User,
  kind: 'access' | 'refresh',
) {
  const value = `mock.${user.role}.${user.id}.${kind}.${randomUUID()}`;
  state.tokens.set(value, {
    userId: user.id,
    kind,
    expires: Date.now() + (kind === 'access' ? 3600 : 604800) * 1000,
  });
  return value;
}
export function authenticate(
  state: MockState,
  value: string | undefined,
  kind: 'access' | 'refresh' = 'access',
): User | undefined {
  const session = value ? state.tokens.get(value) : undefined;
  if (!session || session.kind !== kind || session.expires <= Date.now())
    return undefined;
  return state.users.find((u) => u.id === session.userId);
}
export function paginate<T>(rows: T[], query: Request['query']): ApiList<T> {
  const { page, limit } = parse(
    z.object({
      page: z.coerce.number().int().min(1).default(1),
      limit: z.coerce.number().int().min(1).max(100).default(20),
    }),
    query,
  );
  return {
    data: rows.slice((page - 1) * limit, page * limit),
    pagination: {
      total: rows.length,
      page,
      limit,
      total_pages: Math.ceil(rows.length / limit),
    },
  };
}
export const bearer = (req: Request) =>
  req.get('authorization')?.replace(/^Bearer /, '');
export function routes(app: Express, state: MockState) {
  const paths: { path: string; regex: RegExp; methods: Set<string> }[] = [];
  function route(
    method: 'get' | 'post' | 'patch' | 'delete',
    path: string,
    role: 'public' | 'citizen' | 'police' | 'admin' | 'refresh',
    handler: (req: Request, res: Response, user: User) => unknown,
  ) {
    let record = paths.find((p) => p.path === path);
    if (!record) {
      record = {
        path,
        regex: new RegExp(
          '^/api/v1' + path.replace(/:[^/]+/g, '[^/]+') + '/?$',
        ),
        methods: new Set(),
      };
      paths.push(record);
    }
    record.methods.add(method.toUpperCase());
    app[method]('/api/v1' + path, async (req, res, next) => {
      try {
        const user = authenticate(
          state,
          bearer(req),
          role === 'refresh' ? 'refresh' : 'access',
        );
        if (role !== 'public') {
          if (!user) fail(401, 'UNAUTHENTICATED', 'Please sign in.');
          if (!user.is_active) fail(403, 'FORBIDDEN', 'Account is disabled.');
          if (
            (role === 'admin' && user.role !== 'admin') ||
            (role === 'police' && user.role === 'citizen')
          )
            fail(403, 'FORBIDDEN', 'This role cannot perform this action.');
        }
        await handler(req, res, user as User);
      } catch (error) {
        next(error);
      }
    });
  }
  function finish() {
    app.use((req, _res, next) => {
      const matches = paths.filter((p) => p.regex.test(req.path));
      next(
        matches.length
          ? new HttpError(405, 'METHOD_NOT_ALLOWED', 'Method not allowed.')
          : new HttpError(404, 'NOT_FOUND', 'Not found.'),
      );
    });
    app.use(
      (error: unknown, _req: Request, res: Response, _next: NextFunction) => {
        void _next; // Express identifies error middleware by its four-argument arity.
        if (error instanceof HttpError) {
          res.status(error.status).json({
            error: {
              code: error.code,
              message: error.message,
              ...(error.details ? { details: error.details } : {}),
            },
          });
          return;
        }
        const status =
          typeof error === 'object' && error !== null && 'status' in error
            ? error.status
            : 500;
        res.status(status === 413 ? 413 : status === 400 ? 400 : 500).json({
          error: {
            code:
              status === 413
                ? 'PAYLOAD_TOO_LARGE'
                : status === 400
                  ? 'BAD_REQUEST'
                  : 'INTERNAL',
            message:
              status === 413
                ? 'Upload is too large.'
                : status === 400
                  ? 'Malformed request.'
                  : 'Mock server error.',
          },
        });
        if (status === 500) console.error(error);
      },
    );
  }
  return { route, finish };
}

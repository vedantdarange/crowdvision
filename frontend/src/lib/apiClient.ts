import type { ApiError, ErrorCode } from '@contract/types';
import { API_BASE } from './constants';

export class ApiRequestError extends Error {
  readonly status: number;
  readonly code: ErrorCode;
  readonly details?: ApiError['error']['details'];

  constructor(status: number, error: ApiError['error']) {
    super(error.message);
    this.name = 'ApiRequestError';
    this.status = status;
    this.code = error.code;
    this.details = error.details;
  }
}

export interface ApiOptions extends Omit<RequestInit, 'body'> {
  body?: unknown;
  token?: string;
}

/** Returns the complete contract envelope (including pagination); 204 returns undefined.
 * F1 TODO: session token provider, single-flight refresh, retry once and logout.
 * F0 intentionally surfaces 401 to the caller rather than pretending to refresh.
 */
export async function apiClient<T>(
  path: string,
  options: ApiOptions = {},
): Promise<T> {
  const { body, token, ...init } = options;
  const headers = new Headers(init.headers);
  if (token) headers.set('Authorization', `Bearer ${token}`);
  let requestBody: BodyInit | undefined;
  if (body instanceof FormData) {
    headers.delete('Content-Type');
    requestBody = body;
  } else if (body !== undefined) {
    headers.set('Content-Type', 'application/json');
    requestBody = JSON.stringify(body);
  }
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
    body: requestBody,
  });
  if (response.status === 204) return undefined as T;
  const payload: unknown = await response.json();
  if (!response.ok) {
    const error = payload as ApiError;
    throw new ApiRequestError(response.status, error.error);
  }
  return payload as T;
}

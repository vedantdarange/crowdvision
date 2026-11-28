import type { ApiError, ErrorCode } from '@contract/types';
import { API_BASE } from './constants';

export class ApiRequestError extends Error {
  readonly status: number;
  readonly code: ErrorCode;
  readonly details?: ApiError['error']['details'];
  readonly retryAfterSeconds?: number;

  constructor(
    status: number,
    error: ApiError['error'],
    retryAfterSeconds?: number,
  ) {
    super(error.message);
    this.name = 'ApiRequestError';
    this.status = status;
    this.code = error.code;
    this.details = error.details;
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

function parseRetryAfter(value: string | null): number | undefined {
  if (!value) return undefined;
  const seconds = Number(value);
  if (Number.isFinite(seconds) && seconds > 0) {
    return Math.ceil(seconds);
  }
  const timestamp = Date.parse(value);
  if (Number.isFinite(timestamp)) {
    const diff = Math.ceil((timestamp - Date.now()) / 1000);
    return diff > 0 ? diff : undefined;
  }
  return undefined;
}

export interface ApiOptions extends Omit<RequestInit, 'body'> {
  body?: unknown;
  token?: string;
  responseType?: 'blob';
}

export async function request<T>(
  path: string,
  options: ApiOptions = {},
): Promise<T> {
  const { body, token, responseType, ...init } = options;
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
  if (response.ok && responseType === 'blob')
    return (await response.blob()) as T;
  const payload: unknown = await response.json();
  if (!response.ok) {
    const error = payload as ApiError;
    throw new ApiRequestError(
      response.status,
      error.error,
      parseRetryAfter(response.headers.get('Retry-After')),
    );
  }
  return payload as T;
}

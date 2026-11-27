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

export async function request<T>(
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

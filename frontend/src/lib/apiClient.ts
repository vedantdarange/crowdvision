import { toast } from 'sonner';
import { useSession } from '@/features/auth/session';
import { refresh } from '@/features/auth/api';
import { loginPath } from '@/features/auth/access';
import { ApiRequestError, request, type ApiOptions } from './request';
export { ApiRequestError, type ApiOptions } from './request';

let pending: { generation: number; promise: Promise<void> } | undefined;
function expire(generation: number) {
  const state = useSession.getState();
  if (state.generation !== generation) return;
  state.logout();
  // Hand the redirect to the SPA so the expiry toast survives navigation.
  window.dispatchEvent(
    new CustomEvent('cv:session-expired', {
      detail: loginPath(location.pathname + location.search + location.hash),
    }),
  );
  toast.error('Session expired. Please sign in again.');
}
function unauthenticated(error: unknown) {
  return (
    error instanceof ApiRequestError &&
    error.status === 401 &&
    error.code === 'UNAUTHENTICATED'
  );
}
export async function refreshSession() {
  const { tokens, generation } = useSession.getState();
  if (!tokens) return;
  if (pending?.generation !== generation) {
    const promise = refresh(tokens.refresh_token)
      .then(({ data }) => {
        if (useSession.getState().generation === generation)
          useSession.getState().updateAccess(data.access_token);
      })
      .catch((failure) => {
        expire(generation);
        throw failure;
      })
      .finally(() => {
        if (pending?.generation === generation) pending = undefined;
      });
    pending = { generation, promise };
  }
  await pending.promise;
}
export async function apiClient<T>(
  path: string,
  options: ApiOptions = {},
): Promise<T> {
  const { tokens, generation } = useSession.getState();
  const token = options.token ?? tokens?.access_token;
  try {
    return await request<T>(path, { ...options, token });
  } catch (error) {
    if (
      !tokens ||
      options.token ||
      !unauthenticated(error) ||
      generation !== useSession.getState().generation
    )
      throw error;
    if (useSession.getState().tokens?.access_token === token) {
      await refreshSession();
    }
    if (generation !== useSession.getState().generation) throw error;
    try {
      return await request<T>(path, {
        ...options,
        token: useSession.getState().tokens?.access_token,
      });
    } catch (retryError) {
      if (unauthenticated(retryError)) expire(generation);
      throw retryError;
    }
  }
}

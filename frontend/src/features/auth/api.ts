import type { AccessToken, ApiOne, AuthSession, User } from '@contract/types';
import { request } from '@/lib/request';
import { apiClient } from '@/lib/apiClient';
import { useSession } from './session';

type Credentials = { email: string; password: string };
export const login = (body: Credentials) =>
  request<ApiOne<AuthSession>>('/auth/login', { method: 'POST', body });
export const registerCitizen = (body: Credentials & { name: string }) =>
  request<ApiOne<AuthSession>>('/auth/register', { method: 'POST', body });
export const refresh = (token: string) =>
  request<ApiOne<AccessToken>>('/auth/refresh', { method: 'POST', token });
export const me = () => apiClient<ApiOne<User>>('/auth/me');

export async function restoreSession() {
  const session = useSession.getState();
  if (!session.tokens) return;
  try {
    const { data: user } = await me();
    if (session.generation === useSession.getState().generation)
      useSession.setState({ user });
  } catch {
    if (session.generation === useSession.getState().generation)
      session.logout();
  }
}

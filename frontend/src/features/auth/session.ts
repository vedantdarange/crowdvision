import { create } from 'zustand';
import type { AuthSession, User } from '@contract/types';
import { queryClient } from '@/lib/queryClient';
import { unsubscribePushOnLogout } from '@/features/push/pushApi';

type Tokens = Pick<AuthSession, 'access_token' | 'refresh_token'>;
const storageKey = 'cv-auth';
function restore(): Tokens | null {
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) ?? 'null');
    if (
      typeof saved?.access_token === 'string' &&
      typeof saved?.refresh_token === 'string'
    )
      return {
        access_token: saved.access_token,
        refresh_token: saved.refresh_token,
      };
  } catch {
    /* Storage can be disabled. */
  }
  return null;
}
function persist(tokens: Tokens | null) {
  try {
    if (tokens) localStorage.setItem(storageKey, JSON.stringify(tokens));
    else localStorage.removeItem(storageKey);
  } catch {
    /* The in-memory session still works. */
  }
}
interface Session {
  tokens: Tokens | null;
  user: User | null;
  generation: number;
  logoutFromPath: string | null;
  signIn: (session: AuthSession) => void;
  logout: (options?: { manualFrom?: string }) => void;
  clearLogoutFromPath: () => void;
  updateAccess: (token: string) => void;
}
export const useSession = create<Session>((set, get) => ({
  tokens: restore(),
  user: null,
  generation: 0,
  logoutFromPath: null,
  signIn: ({ access_token, refresh_token, user }) => {
    const tokens = { access_token, refresh_token };
    persist(tokens);
    queryClient.clear();
    set({
      tokens,
      user,
      generation: get().generation + 1,
      logoutFromPath: null,
    });
  },
  logout: (options) => {
    const currentToken = get().tokens?.access_token;
    const currentRole = get().user?.role;
    void unsubscribePushOnLogout(currentToken, currentRole);
    persist(null);
    queryClient.clear();
    set({
      tokens: null,
      user: null,
      generation: get().generation + 1,
      logoutFromPath: options?.manualFrom ?? null,
    });
  },
  clearLogoutFromPath: () => {
    if (get().logoutFromPath !== null) {
      set({ logoutFromPath: null });
    }
  },
  updateAccess: (access_token) => {
    const current = get().tokens;
    if (!current) return;
    const tokens = { ...current, access_token };
    persist(tokens);
    set({ tokens });
  },
}));

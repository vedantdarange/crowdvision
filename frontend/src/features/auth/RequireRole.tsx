import type { ReactNode } from 'react';
import type { Role } from '@contract/types';
import { Navigate, useLocation } from 'react-router';
import { useSession } from './session';
import { allows, loginPath } from './access';
import { AccessPage } from './AccessPage';
export function RequireRole({
  role,
  children,
}: {
  role: Role;
  children: ReactNode;
}) {
  const { user, tokens, logoutFromPath } = useSession();
  const location = useLocation();
  if (!user && tokens) return <p role="status">Checking your session…</p>;
  if (!user) {
    const currentPath = location.pathname + location.search + location.hash;
    if (logoutFromPath === currentPath) {
      return <Navigate replace to="/" />;
    }
    return <Navigate replace to={loginPath(currentPath)} />;
  }
  return allows(user.role, role) ? (
    children
  ) : (
    <main>
      <AccessPage />
    </main>
  );
}

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
  const { user, tokens } = useSession();
  const location = useLocation();
  if (!user && tokens) return <p role="status">Checking your session…</p>;
  if (!user)
    return (
      <Navigate
        replace
        to={loginPath(location.pathname + location.search + location.hash)}
      />
    );
  return allows(user.role, role) ? (
    children
  ) : (
    <main>
      <AccessPage />
    </main>
  );
}

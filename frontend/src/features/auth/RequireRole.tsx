import type { ReactNode } from 'react';
import type { Role } from '@contract/types';
/** F0 scaffold only. F1 replaces this with authenticated session and role checks.
 * This is not an authorization boundary; the mock REST API enforces roles.
 */
export function RequireRole({ children }: { role: Role; children: ReactNode }) {
  return children;
}

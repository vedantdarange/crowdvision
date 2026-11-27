import type { Role } from '@contract/types';
const rank = { citizen: 1, police: 2, admin: 3 };
export const allows = (role: Role, required: Role) =>
  rank[role] >= rank[required];
export const home = (role: Role) =>
  ({ citizen: '/', police: '/police', admin: '/admin/zones' })[role];
export const loginPath = (path: string) =>
  '/login?next=' + encodeURIComponent(path);

import { useMatch } from 'react-router';
import { RequireRole } from '@/features/auth';
import { AlertCenter } from '@/features/alerts/AlertCenter';
import { AppShell } from './AppShell';
export function PoliceLayout() {
  const admin = useMatch('/admin/*');
  return (
    <RequireRole role={admin ? 'admin' : 'police'}>
      <AppShell audience={admin ? 'admin' : 'police'}>
        <AlertCenter />
      </AppShell>
    </RequireRole>
  );
}

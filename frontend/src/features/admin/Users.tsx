import { useDeferredValue, useState } from 'react';
import { useForm } from 'react-hook-form';
import { z } from 'zod';
import { zodResolver } from '@hookform/resolvers/zod';
import type { Role, User } from '@contract/types';
import { Button } from '@/components/ui/button';
import { useSession } from '@/features/auth';
import { ApiRequestError } from '@/lib/apiClient';
import { ManagementPage, Pager, WriteError } from './ManagementLayout';
import { useUsers, useWriteUser } from './managementApi';

const createSchema = z.object({
  name: z.string().trim().min(1),
  email: z.email(),
  password: z.string().min(8),
  role: z.enum(['police', 'admin']),
});
function CreateUser() {
  const form = useForm<z.infer<typeof createSchema>>({
    resolver: zodResolver(createSchema),
    defaultValues: { role: 'police' },
  });
  const write = useWriteUser();
  return (
    <form
      className="glass space-y-3"
      onSubmit={form.handleSubmit((body) =>
        write.mutate(
          { body },
          {
            onSuccess: () => form.reset(),
            onError: (error) => {
              if (error instanceof ApiRequestError && error.status === 409)
                form.setError(
                  'email',
                  { message: 'An account already uses this email.' },
                  { shouldFocus: true },
                );
            },
          },
        ),
      )}
    >
      <h2>Create staff account</h2>
      <fieldset disabled={write.isPending} className="police-filters">
        {(['name', 'email', 'password'] as const).map((key) => (
          <label key={key}>
            {
              {
                name: 'Name',
                email: 'Email',
                password: 'Temporary password (8+ characters)',
              }[key]
            }
            <input
              {...form.register(key)}
              required
              type={key === 'name' ? 'text' : key}
              autoComplete={key === 'password' ? 'new-password' : 'off'}
              minLength={key === 'password' ? 8 : 1}
            />
            {form.formState.errors[key] && (
              <span role="alert">{form.formState.errors[key]?.message}</span>
            )}
          </label>
        ))}
        <label>
          Account role
          <select {...form.register('role')}>
            <option value="police">Police</option>
            <option value="admin">Admin</option>
          </select>
        </label>
        <Button>Create account</Button>
      </fieldset>
      <WriteError error={write.error} />
    </form>
  );
}
const roles: Role[] = ['citizen', 'police', 'admin'];
function UserRow({ user, self }: { user: User; self: boolean }) {
  const write = useWriteUser();
  return (
    <li className="glass space-y-2">
      <h3>{user.name}</h3>
      <p className="break-all">
        {user.email} · {user.is_active ? 'Active' : 'Inactive'}
      </p>
      <div className="police-filters">
        <label>
          Role for {user.name}
          <select
            disabled={self || write.isPending}
            value={user.role}
            onChange={(e) =>
              write.mutate({
                id: user.id,
                body: { role: e.target.value as Role },
              })
            }
          >
            {roles.map((r) => (
              <option key={r}>{r}</option>
            ))}
          </select>
        </label>
        <Button
          variant="outline"
          disabled={self || write.isPending}
          onClick={() =>
            write.mutate({ id: user.id, body: { is_active: !user.is_active } })
          }
        >
          {user.is_active ? 'Disable' : 'Enable'} {user.name}
        </Button>
      </div>
      {self && (
        <p>Your account is protected so you retain administrator access.</p>
      )}
      <WriteError error={write.error} />
    </li>
  );
}
function Directory() {
  const [filters, set] = useState({
    q: '',
    role: '',
    is_active: '',
    page: '1',
  });
  const self = useSession((s) => s.user?.id);
  const { data } = useUsers(useDeferredValue(filters));
  function filter(key: keyof typeof filters, value: string) {
    set({ ...filters, page: '1', [key]: value });
  }
  return (
    <>
      <div className="police-filters">
        <label>
          Search name or email
          <input
            type="search"
            value={filters.q}
            onChange={(e) => filter('q', e.target.value)}
          />
        </label>
        <label>
          Filter by role
          <select
            value={filters.role}
            onChange={(e) => filter('role', e.target.value)}
          >
            <option value="">All roles</option>
            {roles.map((r) => (
              <option key={r}>{r}</option>
            ))}
          </select>
        </label>
        <label>
          Account status
          <select
            value={filters.is_active}
            onChange={(e) => filter('is_active', e.target.value)}
          >
            <option value="">All statuses</option>
            <option value="true">Active</option>
            <option value="false">Inactive</option>
          </select>
        </label>
      </div>
      {data.data.length ? (
        <ul className="grid gap-3 md:grid-cols-2">
          {data.data.map((user) => (
            <UserRow key={user.id} user={user} self={self === user.id} />
          ))}
        </ul>
      ) : (
        <p>
          No matching accounts. Adjust your filters or create a staff account.
        </p>
      )}
      <Pager
        data={data.pagination}
        setPage={(p) => filter('page', String(p))}
      />
    </>
  );
}
export function Component() {
  return (
    <ManagementPage title="Users">
      <CreateUser />
      <Directory />
    </ManagementPage>
  );
}

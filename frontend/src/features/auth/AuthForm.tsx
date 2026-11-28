import { useState } from 'react';
import { Link, matchRoutes, Navigate, useSearchParams } from 'react-router';
import { useForm } from 'react-hook-form';
import { z } from 'zod';
import { zodResolver } from '@hookform/resolvers/zod';
import type { Role } from '@contract/types';
import { routes } from '@/app/router';
import { ApiRequestError } from '@/lib/apiClient';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { login, registerCitizen } from './api';
import { useSession } from './session';
import { allows, home } from './access';

function destination(next: string | null, role: Role) {
  if (!next?.startsWith('/') || /^\/\/|[\\\x00-\x1f]/.test(next))
    return home(role);
  const url = new URL(next, location.origin);
  const matches = matchRoutes(routes, url.pathname);
  const leaf = matches?.at(-1)?.route;
  if (
    url.origin !== location.origin ||
    url.pathname.startsWith('//') ||
    !leaf ||
    ['*', '/login', '/register', '/forbidden'].includes(leaf.path ?? '')
  )
    return home(role);
  if (
    matches?.some(
      (m) => m.route.handle?.role && !allows(role, m.route.handle.role),
    )
  )
    return home(role);
  return url.pathname + url.search + url.hash;
}
const credentials = z.object({
  name: z.string(),
  email: z.email('Enter a valid email address.'),
  password: z.string().min(1, 'Enter your password.'),
});
const registration = credentials.extend({
  name: z.string().trim().min(1, 'Enter your name.'),
  password: z.string().min(8, 'Use at least 8 characters.'),
});
type Values = z.infer<typeof credentials>;
const messages: Record<number, string> = {
  401: 'Email or password is incorrect.',
  403: 'Your account is disabled. Contact an administrator.',
  409: 'This email is already registered.',
  429: 'Too many attempts. Please try again later.',
};
function AuthForm({ creating = false }: { creating?: boolean }) {
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<Values>({
    resolver: zodResolver(creating ? registration : credentials),
    defaultValues: { name: '', email: '', password: '' },
  });
  const [visible, setVisible] = useState(false);
  const [params] = useSearchParams();
  const next = params.get('next');
  const user = useSession((s) => s.user);
  const tokens = useSession((s) => s.tokens);
  if (user) return <Navigate replace to={destination(next, user.role)} />;
  if (tokens) return <p role="status">Checking your session…</p>;
  async function submit(values: Values) {
    try {
      const { data } = creating
        ? await registerCitizen(values)
        : await login({ email: values.email, password: values.password });
      useSession.getState().signIn(data);
    } catch (error) {
      if (error instanceof ApiRequestError) {
        if (error.status === 422) {
          let mapped = false;
          for (const field of ['email', 'password', 'name'] as const) {
            const detail = error.details?.[field];
            if (
              (field !== 'name' || creating) &&
              Array.isArray(detail) &&
              typeof detail[0] === 'string'
            ) {
              setError(field, { message: detail[0] }, { shouldFocus: !mapped });
              mapped = true;
            }
          }
          if (mapped) return;
        }
        setError('root', { message: messages[error.status] ?? error.message });
      } else
        setError('root', { message: 'Could not connect. Please try again.' });
    }
  }
  const title = creating ? 'Create citizen account' : 'Sign in';
  return (
    <section className="mx-auto my-8 max-w-md rounded-3xl border bg-card p-6 text-card-foreground">
      <h1 className="mb-6 text-3xl font-semibold">{title}</h1>
      <form noValidate onSubmit={handleSubmit(submit)} className="grid gap-4">
        {(['name', 'email', 'password'] as const)
          .filter((key) => creating || key !== 'name')
          .map((key) => (
            <div className="grid gap-2" key={key}>
              <Label htmlFor={key}>
                {{ name: 'Name', email: 'Email', password: 'Password' }[key]}
              </Label>
              <Input
                id={key}
                type={
                  key === 'password'
                    ? visible
                      ? 'text'
                      : 'password'
                    : key === 'email'
                      ? 'email'
                      : 'text'
                }
                autoComplete={
                  key === 'password'
                    ? creating
                      ? 'new-password'
                      : 'current-password'
                    : key
                }
                aria-invalid={!!errors[key]}
                aria-describedby={errors[key] ? key + '-error' : undefined}
                {...register(key)}
              />
              {errors[key] && (
                <p id={key + '-error'} role="alert">
                  {errors[key].message}
                </p>
              )}
            </div>
          ))}
        <button
          type="button"
          className="min-h-11 justify-self-start underline"
          aria-pressed={visible}
          onClick={() => setVisible(!visible)}
        >
          {visible ? 'Hide' : 'Show'} password
        </button>
        {errors.root && <p role="alert">{errors.root.message}</p>}
        <Button type="submit" className="min-h-11" disabled={isSubmitting}>
          {isSubmitting
            ? creating
              ? 'Creating account…'
              : 'Signing in…'
            : title}
        </Button>
      </form>
      <Link
        className="mt-2 inline-flex min-h-11 items-center underline"
        to={{
          pathname: creating ? '/login' : '/register',
          search: params.toString(),
        }}
      >
        {creating ? 'Sign in' : 'Create citizen account'}
      </Link>
    </section>
  );
}
export function LoginForm() {
  return <AuthForm />;
}
export function RegisterForm() {
  return <AuthForm creating />;
}

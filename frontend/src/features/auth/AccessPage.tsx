import { Link } from 'react-router';
import { home } from './access';
import { useSession } from './session';

export function AccessPage({ missing = false }: { missing?: boolean }) {
  const user = useSession((s) => s.user);
  return (
    <section className="mx-auto max-w-lg p-6">
      <h1 className="text-3xl font-semibold">
        {missing ? 'Page not found' : 'Forbidden'}
      </h1>
      <p className="my-4">
        {missing
          ? 'This page could not be found.'
          : 'Your account does not have access to this page.'}
      </p>
      <Link className="underline" to={user ? home(user.role) : '/'}>
        Return home
      </Link>
    </section>
  );
}

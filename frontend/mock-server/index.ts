import { randomBytes } from 'node:crypto';
import { createMockServer } from './server';
try {
  process.loadEnvFile('.env');
} catch {
  /* Optional local .env. */
}
if (process.env.NODE_ENV === 'production')
  throw new Error('The mock server must never run in production.');
const password =
  process.env.SEED_PASSWORD ?? randomBytes(12).toString('base64url');
const server = createMockServer({ password });
server.http.listen(5001, '127.0.0.1', () => {
  process.stdout.write(
    'Crowd Safety mock listening at http://127.0.0.1:5001 (contract 1.1.0)\n',
  );
  if (!process.env.SEED_PASSWORD)
    process.stdout.write(`Generated mock seed password: ${password}\n`);
});
for (const signal of ['SIGINT', 'SIGTERM'] as const)
  process.once(signal, () => {
    void server.close().then(() => process.exit(0));
  });

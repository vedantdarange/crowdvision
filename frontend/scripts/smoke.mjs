import { io } from 'socket.io-client';
const origin = 'http://localhost:5173';
const health = await fetch(origin + '/api/v1/health');
if (!health.ok || (await health.json()).status !== 'ok')
  throw new Error('Vite REST proxy failed');
const socket = io(origin, { transports: ['websocket'], autoConnect: false });
try {
  const hello = await new Promise((resolve, reject) => {
    const timer = setTimeout(
      () => reject(new Error('Socket hello timed out')),
      5000,
    );
    socket.once('hello', (payload) => {
      clearTimeout(timer);
      resolve(payload);
    });
    socket.once('connect_error', reject);
    socket.connect();
  });
  if (hello.contract_version !== '1.1.0' || hello.role !== null)
    throw new Error('Unexpected hello');
  for (const path of ['/', '/login', '/police/alerts/12', '/admin/zones/new']) {
    const response = await fetch(origin + path);
    if (
      !response.ok ||
      !(await response.text()).includes('Crowd Safety Monitor')
    )
      throw new Error('SPA fallback failed: ' + path);
  }
  process.stdout.write(
    'PASS: Vite REST + WebSocket proxies, public hello 1.1.0, and four SPA deep links.\n',
  );
} finally {
  socket.disconnect();
}

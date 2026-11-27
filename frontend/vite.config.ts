import { fileURLToPath, URL } from 'node:url';
import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_');
  const target =
    (process.env.VITE_USE_MOCKS ?? env.VITE_USE_MOCKS) === '1'
      ? 'http://127.0.0.1:5001'
      : 'http://127.0.0.1:5000';
  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
        '@contract': fileURLToPath(new URL('../contract', import.meta.url)),
      },
    },
    server: {
      fs: {
        allow: [
          fileURLToPath(new URL('.', import.meta.url)),
          fileURLToPath(new URL('../contract', import.meta.url)),
        ],
      },
      port: 5173,
      strictPort: true,
      proxy: {
        '/api': { target },
        '/socket.io': { target, ws: true },
      },
    },
  };
});

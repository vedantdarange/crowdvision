import { fileURLToPath, URL } from 'node:url';
import { defineConfig, loadEnv, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { VitePWA } from 'vite-plugin-pwa';

function noCacheSwPreview(): Plugin {
  return {
    name: 'cv-no-cache-sw-preview',
    configurePreviewServer(server) {
      server.middlewares.use((req, res, next) => {
        if (
          req.url === '/sw.js' ||
          req.url === '/' ||
          req.url === '/index.html'
        ) {
          res.setHeader('Cache-Control', 'no-cache');
        }
        next();
      });
    },
  };
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_');
  const target =
    (process.env.VITE_USE_MOCKS ?? env.VITE_USE_MOCKS) === '1'
      ? 'http://127.0.0.1:5001'
      : 'http://127.0.0.1:5000';
  return {
    plugins: [
      react(),
      tailwindcss(),
      VitePWA({
        strategies: 'injectManifest',
        srcDir: 'src',
        filename: 'sw.ts',
        injectRegister: false,
        includeAssets: ['favicon.svg', 'icons/apple-touch-icon.png'],
        manifest: {
          name: 'Crowd Safety Monitor',
          short_name: 'Crowd Monitor',
          description:
            'Real-time crowd density monitoring, emergency alerts, and responder coordination.',
          start_url: '/',
          scope: '/',
          display: 'standalone',
          theme_color: '#0f766e',
          background_color: '#09090b',
          icons: [
            {
              src: '/icons/icon-192.png',
              sizes: '192x192',
              type: 'image/png',
              purpose: 'any',
            },
            {
              src: '/icons/icon-512.png',
              sizes: '512x512',
              type: 'image/png',
              purpose: 'any',
            },
            {
              src: '/icons/icon-512-maskable.png',
              sizes: '512x512',
              type: 'image/png',
              purpose: 'maskable',
            },
          ],
        },
        injectManifest: {
          globPatterns: ['**/*.{js,css,html,svg,png,woff2,webmanifest}'],
        },
      }),
      noCacheSwPreview(),
    ],
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

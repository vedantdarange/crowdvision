/// <reference lib="webworker" />
import { clientsClaim } from 'workbox-core';
import {
  cleanupOutdatedCaches,
  createHandlerBoundToURL,
  precacheAndRoute,
  type PrecacheEntry,
} from 'workbox-precaching';
import { NavigationRoute, registerRoute } from 'workbox-routing';
import {
  API_OR_SOCKET_DENYLIST,
  handleNotificationClick,
  handlePushEvent,
} from '@/features/push/swHandlers';

declare let self: ServiceWorkerGlobalScope & {
  __WB_MANIFEST: Array<PrecacheEntry | string>;
};

precacheAndRoute(self.__WB_MANIFEST);
cleanupOutdatedCaches();

// Never intercept backend API or Socket.IO navigations with the SPA shell.
registerRoute(
  new NavigationRoute(createHandlerBoundToURL('/index.html'), {
    denylist: [...API_OR_SOCKET_DENYLIST],
  }),
);

self.addEventListener('install', () => {
  void self.skipWaiting();
});

clientsClaim();

self.addEventListener('message', (event) => {
  const data = event.data as { type?: unknown } | null | undefined;
  if (data?.type === 'SKIP_WAITING') {
    void self.skipWaiting();
  }
});

self.addEventListener('push', (event) => {
  handlePushEvent(event, self.registration);
});

self.addEventListener('notificationclick', (event) => {
  handleNotificationClick(event, self.clients, self.location.origin);
});

import { toast } from 'sonner';
import { registerSW, type RegisterSWOptions } from 'virtual:pwa-register';

export type RegisterSwFn = (
  options?: RegisterSWOptions,
) => (reloadPage?: boolean) => Promise<void>;

export interface SetupPwaOptions {
  registerFn?: RegisterSwFn;
  onUpdateAvailable?: (applyUpdate: () => Promise<void>) => void;
  doc?: Document;
}

let pwaRegistered = false;

/** Registers SW update lifecycle handlers using a given registerSW implementation. */
export function setupPwaRegistration({
  registerFn = registerSW,
  onUpdateAvailable,
  doc = typeof document !== 'undefined' ? document : undefined,
}: SetupPwaOptions = {}): () => void {
  let activeRegistration: ServiceWorkerRegistration | undefined;

  const updateSW = registerFn({
    immediate: true,
    onNeedRefresh() {
      const applyUpdate = () => updateSW(true);
      if (onUpdateAvailable) {
        onUpdateAvailable(applyUpdate);
        return;
      }
      toast('App update available', {
        description: 'Reload to switch to the latest version.',
        duration: Infinity,
        action: {
          label: 'Update',
          onClick: () => {
            void applyUpdate();
          },
        },
      });
    },
    onRegisteredSW(_swUrl, registration) {
      activeRegistration = registration;
    },
  });

  if (!doc) return () => {};

  const handleVisibilityChange = () => {
    if (doc.visibilityState === 'visible' && activeRegistration) {
      void activeRegistration.update().catch(() => undefined);
    }
  };
  doc.addEventListener('visibilitychange', handleVisibilityChange);
  return () => {
    doc.removeEventListener('visibilitychange', handleVisibilityChange);
  };
}

/** Registers the service worker in production builds without polluting dev mode. */
export function registerPwa(): void {
  if (pwaRegistered) return;
  if (!import.meta.env.PROD) return;
  if (typeof navigator === 'undefined' || !('serviceWorker' in navigator)) {
    return;
  }
  pwaRegistered = true;
  setupPwaRegistration();
}

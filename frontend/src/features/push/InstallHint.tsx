import { useEffect, useState } from 'react';
import { Download, Share, X } from 'lucide-react';

export interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed'; platform: string }>;
}

const DISMISS_STORAGE_KEY = 'cv-install-hint-dismissed';

export function isIosSafari(
  userAgent = typeof navigator !== 'undefined' ? navigator.userAgent : '',
  maxTouchPoints = typeof navigator !== 'undefined'
    ? navigator.maxTouchPoints
    : 0,
): boolean {
  const isIosDevice =
    /iP(ad|hone|od)/i.test(userAgent) ||
    (/Macintosh/i.test(userAgent) && maxTouchPoints > 1);
  if (!isIosDevice) return false;
  const isSafari = /Safari/i.test(userAgent);
  const isOtherIosBrowser = /CriOS|FxiOS|EdgiOS|OPiOS|DuckDuckGo/i.test(
    userAgent,
  );
  return isSafari && !isOtherIosBrowser;
}

export function isStandaloneDisplayMode(): boolean {
  if (typeof window === 'undefined') return false;
  const mediaStandalone =
    window.matchMedia?.('(display-mode: standalone)')?.matches ?? false;
  const iosStandalone =
    (navigator as Navigator & { standalone?: boolean }).standalone === true;
  return mediaStandalone || iosStandalone;
}

function isDismissed(): boolean {
  try {
    return window.sessionStorage?.getItem(DISMISS_STORAGE_KEY) === '1';
  } catch {
    return false;
  }
}

function rememberDismissed(): void {
  try {
    window.sessionStorage?.setItem(DISMISS_STORAGE_KEY, '1');
  } catch {
    // Ignore storage unavailability in private contexts.
  }
}

/** Shows Android Chrome install prompt when available, or iOS Add to Home Screen guidance. */
export function InstallHint() {
  const [deferredPrompt, setDeferredPrompt] =
    useState<BeforeInstallPromptEvent | null>(null);
  const [dismissed, setDismissed] = useState<boolean>(isDismissed);
  const [standalone, setStandalone] = useState<boolean>(
    isStandaloneDisplayMode,
  );
  const iosSafari = isIosSafari();

  useEffect(() => {
    setStandalone(isStandaloneDisplayMode());

    function handleBeforeInstallPrompt(event: Event) {
      event.preventDefault();
      setDeferredPrompt(event as BeforeInstallPromptEvent);
    }

    function handleAppInstalled() {
      setDeferredPrompt(null);
      setStandalone(true);
    }

    window.addEventListener('beforeinstallprompt', handleBeforeInstallPrompt);
    window.addEventListener('appinstalled', handleAppInstalled);
    return () => {
      window.removeEventListener(
        'beforeinstallprompt',
        handleBeforeInstallPrompt,
      );
      window.removeEventListener('appinstalled', handleAppInstalled);
    };
  }, []);

  if (dismissed || standalone) return null;
  if (!deferredPrompt && !iosSafari) return null;

  async function handleInstall() {
    if (!deferredPrompt) return;
    try {
      await deferredPrompt.prompt();
      const choice = await deferredPrompt.userChoice;
      if (choice.outcome === 'accepted') {
        setStandalone(true);
      }
    } finally {
      setDeferredPrompt(null);
    }
  }

  function handleDismiss() {
    rememberDismissed();
    setDismissed(true);
  }

  return (
    <section
      aria-label="Install app"
      className="mx-auto mt-3 flex max-w-6xl items-center justify-between gap-3 rounded-lg border border-teal-500/30 bg-teal-500/10 px-4 py-2.5 text-sm"
    >
      <div className="flex items-start gap-2.5">
        {deferredPrompt ? (
          <Download size={18} className="mt-0.5 shrink-0" aria-hidden />
        ) : (
          <Share size={18} className="mt-0.5 shrink-0" aria-hidden />
        )}
        <div>
          <p className="font-semibold">Install Crowd Safety Monitor</p>
          {deferredPrompt ? (
            <p className="text-muted-foreground text-xs">
              Install to your home screen for full-screen monitoring and
              reliable background push alerts.
            </p>
          ) : (
            <p className="text-muted-foreground text-xs">
              In Safari tap <strong>Share -&gt; Add to Home Screen</strong>.
              Background push notifications work on iOS 16.4+ only for the
              installed app.
            </p>
          )}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {deferredPrompt && (
          <button
            type="button"
            onClick={() => void handleInstall()}
            className="min-h-11 rounded-md bg-teal-700 px-3 text-xs font-semibold text-white hover:bg-teal-800"
          >
            Install app
          </button>
        )}
        <button
          type="button"
          onClick={handleDismiss}
          aria-label="Dismiss install hint"
          className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-md border hover:bg-muted"
        >
          <X size={16} aria-hidden />
        </button>
      </div>
    </section>
  );
}

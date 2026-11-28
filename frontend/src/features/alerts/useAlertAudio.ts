import { useEffect, useRef, useState } from 'react';

function preference(key: string) {
  try {
    return localStorage.getItem(key) === 'true';
  } catch {
    return false;
  }
}
function remember(key: string, value: boolean) {
  try {
    localStorage.setItem(key, String(value));
  } catch {
    /* Private browsing. */
  }
}

// Each burst has one oscillator. Its frequency changes halfway through the siren.
class AudioOutput {
  readonly context = new AudioContext();
  private voices = new Set<OscillatorNode>();
  play(siren: boolean) {
    const ctx = this.context;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    const t = ctx.currentTime,
      duration = siren ? 0.8 : 0.14;
    osc.frequency.setValueAtTime(siren ? 740 : 550, t);
    if (siren) osc.frequency.setValueAtTime(990, t + 0.4);
    gain.gain.setValueAtTime(0.001, t);
    gain.gain.exponentialRampToValueAtTime(0.1, t + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.001, t + duration);
    osc.connect(gain);
    gain.connect(ctx.destination);
    this.voices.add(osc);
    osc.onended = () => {
      this.voices.delete(osc);
      osc.disconnect();
      gain.disconnect();
    };
    osc.start(t);
    osc.stop(t + duration);
  }
  stop() {
    for (const osc of this.voices) osc.stop();
  }
}

export interface AlertAudioOptions {
  onPermissionResult?: (permission: NotificationPermission) => void;
}

export function useAlertAudio(
  criticalKeys: string,
  warningKeys: string,
  options?: AlertAudioOptions,
) {
  const onPermissionResultRef = useRef(options?.onPermissionResult);
  onPermissionResultRef.current = options?.onPermissionResult;
  const output = useRef<AudioOutput | null>(null);
  const [armed, setArmed] = useState(false);
  const [intent, setIntent] = useState(() => preference('cv-alert-armed'));
  const [muted, setMuted] = useState(() => preference('cv-alert-muted'));
  const [notice, setNotice] = useState('');
  const starts = useRef(new Map<string, { start: number; next: number }>());
  const chimed = useRef(new Set<string>());
  useEffect(
    () => () => {
      const device = output.current;
      output.current = null;
      if (device) {
        device.context.onstatechange = null;
        device.stop();
        void device.context.close().catch(() => {});
      }
    },
    [],
  );
  function arm() {
    remember('cv-alert-armed', true);
    setIntent(true);
    try {
      const device = (output.current ??= new AudioOutput());
      const sync = () => {
        if (output.current === device)
          setArmed(device.context.state === 'running');
      };
      device.context.onstatechange = sync;
      void device.context
        .resume()
        .then(sync)
        .catch(() => setNotice('Tap again to enable sound.'));
      device.play(false);
      sync();
    } catch {
      setNotice('Audio could not start on this device.');
    }
    navigator.vibrate?.(30);
    // F5: subscribe after this permission request succeeds, using the configured VAPID key.
    if (typeof Notification !== 'undefined' && Notification.requestPermission) {
      void Notification.requestPermission()
        .then((permission) => {
          onPermissionResultRef.current?.(permission);
          if (permission === 'denied')
            setNotice('Notifications are blocked in browser settings.');
        })
        .catch(() => setNotice('Notifications are unavailable.'));
    }
  }
  useEffect(() => {
    const device = output.current;
    const critical = criticalKeys.split(',').filter(Boolean);
    const warnings = warningKeys.split(',').filter(Boolean);
    for (const id of starts.current.keys())
      if (!critical.includes(id)) starts.current.delete(id);
    for (const id of chimed.current)
      if (!warnings.includes(id)) chimed.current.delete(id);
    if (!armed || !device) return;
    let timer: ReturnType<typeof setTimeout>;
    const tick = () => {
      const now = Date.now();
      let due = Infinity,
        siren = false;
      for (const id of critical) {
        const clock = starts.current.get(id) ?? { start: now, next: now };
        starts.current.set(id, clock);
        if (now >= clock.start + 60000) continue;
        if (clock.next <= now) {
          siren = true;
          clock.next = now + 10000;
        }
        if (clock.next < clock.start + 60000) due = Math.min(due, clock.next);
      }
      const chime = warnings.some((id) => !chimed.current.has(id));
      warnings.forEach((id) => chimed.current.add(id));
      if (siren || chime) {
        if (!muted) device.play(siren);
        navigator.vibrate?.([300, 100, 300]);
      }
      if (Number.isFinite(due)) timer = setTimeout(tick, due - now);
    };
    tick();
    return () => {
      clearTimeout(timer);
      device.stop();
      navigator.vibrate?.(0);
    };
  }, [armed, criticalKeys, warningKeys, muted]);
  return {
    armed,
    intent,
    muted,
    notice,
    arm,
    toggleMute() {
      remember('cv-alert-muted', !muted);
      setMuted(!muted);
    },
  };
}

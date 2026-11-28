import { useEffect } from 'react';
export function useAlertTitle(count: number) {
  useEffect(() => {
    if (!count) return;
    const original = document.title;
    const emphasis = '(' + count + ' awaiting review) ' + original;
    const motion = window.matchMedia?.('(prefers-reduced-motion: reduce)');
    let timer: ReturnType<typeof setInterval>;
    function apply() {
      clearInterval(timer);
      document.title = emphasis;
      if (!motion?.matches)
        timer = setInterval(() => {
          document.title = document.title === emphasis ? original : emphasis;
        }, 1200);
    }
    apply();
    motion?.addEventListener?.('change', apply);
    return () => {
      clearInterval(timer);
      motion?.removeEventListener?.('change', apply);
      document.title = original;
    };
  }, [count]);
}

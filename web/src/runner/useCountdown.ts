import { useEffect, useRef, useState } from 'react';

/** Counts down from `seconds` while `active`; calls onDone once at zero. */
export function useCountdown(seconds: number, active: boolean, onDone: () => void): number {
  const [left, setLeft] = useState(seconds);
  const cb = useRef(onDone);
  cb.current = onDone;
  useEffect(() => {
    if (!active) return;
    setLeft(seconds);
    const t0 = performance.now();
    const id = setInterval(() => {
      const remaining = seconds - (performance.now() - t0) / 1000;
      if (remaining <= 0) {
        clearInterval(id);
        setLeft(0);
        cb.current();
      } else {
        setLeft(Math.ceil(remaining));
      }
    }, 100);
    return () => clearInterval(id);
  }, [seconds, active]);
  return left;
}


/** Smooth progress for a fixed window: tenths of a second left and percent elapsed, 10 Hz. */
export function useProgress(seconds: number, active: boolean): { left: number; pct: number } {
  const [state, setState] = useState({ left: seconds, pct: 0 });
  useEffect(() => {
    if (!active) {
      setState({ left: seconds, pct: 0 });
      return;
    }
    const t0 = performance.now();
    const id = setInterval(() => {
      const elapsed = (performance.now() - t0) / 1000;
      const left = Math.max(0, seconds - elapsed);
      setState({ left, pct: Math.min(100, (elapsed / seconds) * 100) });
      if (left <= 0) clearInterval(id);
    }, 100);
    return () => clearInterval(id);
  }, [seconds, active]);
  return state;
}

import { useEffect, useRef, useState } from 'react';

export interface TimerState { left: number; pct: number }

/**
 * One timer for every fixed window in the app (prep countdown, recording, typing deadline, the
 * setup checks). While `active`, ticks at 10 Hz with the seconds left and the percent elapsed;
 * calls `onDone` once when the window closes.
 */
export function useTimer(seconds: number, active: boolean, onDone?: () => void): TimerState {
  const [state, setState] = useState<TimerState>({ left: seconds, pct: 0 });
  const cb = useRef(onDone);
  useEffect(() => { cb.current = onDone; });
  useEffect(() => {
    if (!active) return;
    setState({ left: seconds, pct: 0 });
    const t0 = performance.now();
    const id = setInterval(() => {
      const elapsed = (performance.now() - t0) / 1000;
      const left = Math.max(0, seconds - elapsed);
      setState({ left, pct: Math.min(100, (elapsed / seconds) * 100) });
      if (left <= 0) {
        clearInterval(id);
        cb.current?.();
      }
    }, 100);
    return () => clearInterval(id);
  }, [seconds, active]);
  return active ? state : { left: seconds, pct: 0 };
}

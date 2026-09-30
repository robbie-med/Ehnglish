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

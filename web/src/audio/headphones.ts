import { goertzelPower } from './quality';

export interface HeadphoneResult { leak_db: number; ok: boolean; tone_hz: number }

/** Leak threshold: tone energy at the mic more than this above the silence reference = speakers. */
export const LEAK_THRESHOLD_DB = 12;

export function evaluateLeak(withTone: Int16Array, silence: Int16Array, sampleRate: number, toneHz = 1000): HeadphoneResult {
  const pTone = goertzelPower(withTone, sampleRate, toneHz);
  const pRef = goertzelPower(silence, sampleRate, toneHz);
  const floor = 1e-12;
  const leak = 10 * Math.log10((pTone + floor) / (pRef + floor));
  const leak_db = Math.round(leak * 10) / 10;
  return { leak_db, ok: leak_db < LEAK_THRESHOLD_DB, tone_hz: toneHz };
}

import { goertzelPower } from './quality';

export interface HeadphoneResult {
  leak_db: number; // tone level in the mic relative to the same bin during silence
  tone_dbfs: number; // absolute level of the 1 kHz component in the mic
  ok: boolean;
  tone_hz: number;
  override?: boolean; // the learner chose to continue despite a failed check (logged)
}

/**
 * A leak counts only when the tone is BOTH clearly above the silence reference AND loud in
 * absolute terms. Headphones always leak a little (open backs, bone conduction, electrical
 * crosstalk) and that showed up as 20–30 dB over an almost-empty noise bin while being
 * inaudible; what matters is whether test audio could contaminate a recording, i.e. whether it
 * approaches speech level (~-20 dBFS). -38 dBFS is ~18 dB under quiet speech.
 */
export const LEAK_THRESHOLD_DB = 15;
export const LEAK_ABS_DBFS = -38;

export function evaluateLeak(withTone: Int16Array, silence: Int16Array, sampleRate: number, toneHz = 1000): HeadphoneResult {
  const pTone = goertzelPower(withTone, sampleRate, toneHz);
  const pRef = goertzelPower(silence, sampleRate, toneHz);
  const floor = 1e-12;
  const leak = 10 * Math.log10((pTone + floor) / (pRef + floor));
  // goertzelPower is normalised so that a full-scale sine gives ≈0.25 (amplitude² / 4)
  const toneAmp = Math.sqrt(Math.max(pTone, floor) * 4);
  const tone_dbfs = Math.round(20 * Math.log10(toneAmp / Math.SQRT2 + floor) * 10) / 10;
  const leak_db = Math.round(leak * 10) / 10;
  return { leak_db, tone_dbfs, ok: !(leak_db >= LEAK_THRESHOLD_DB && tone_dbfs >= LEAK_ABS_DBFS), tone_hz: toneHz };
}

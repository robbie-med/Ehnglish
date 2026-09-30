/** Per-take quality check: clipping, loudness, noise floor, SNR. Pure function; unit-tested. */

export type QualityFlag = 'clipping' | 'too_loud' | 'too_quiet' | 'noisy' | 'silent';

export interface QualityReport {
  duration_s: number;
  peak_dbfs: number | null;
  rms_dbfs: number | null;
  noise_floor_dbfs: number | null;
  snr_db: number | null;
  clip_count: number;
  clip_ratio: number;
  flags: QualityFlag[];
  ok: boolean;
}

export const THRESHOLDS = {
  clipRatio: 0.001, // >0.1% of samples at full scale
  tooLoudRms: -6,
  tooQuietRms: -35,
  minSnr: 15,
  silentPeak: -50,
};

const dbfs = (v: number): number | null => (v <= 0 ? null : Math.round(20 * Math.log10(v) * 100) / 100);

export function analyzeTake(samples: Int16Array, sampleRate: number, knownNoiseFloorDbfs?: number | null): QualityReport {
  const n = samples.length;
  if (n === 0) {
    return { duration_s: 0, peak_dbfs: null, rms_dbfs: null, noise_floor_dbfs: null, snr_db: null, clip_count: 0, clip_ratio: 0, flags: ['silent'], ok: false };
  }
  let peak = 0;
  let sumSq = 0;
  let clip = 0;
  for (let i = 0; i < n; i++) {
    const x = Math.abs(samples[i]) / 32768;
    if (x > peak) peak = x;
    sumSq += x * x;
    if (x >= 0.999) clip++;
  }
  const rms = Math.sqrt(sumSq / n);
  // Noise floor: 5th percentile of RMS over 50 ms windows.
  const win = Math.max(1, Math.floor(sampleRate / 20));
  const wins: number[] = [];
  for (let s = 0; s + win <= n; s += win) {
    let ss = 0;
    for (let i = s; i < s + win; i++) {
      const x = samples[i] / 32768;
      ss += x * x;
    }
    wins.push(Math.sqrt(ss / win));
  }
  wins.sort((a, b) => a - b);
  let floor = wins.length ? wins[Math.floor(wins.length * 0.05)] : rms;
  if (knownNoiseFloorDbfs != null && Number.isFinite(knownNoiseFloorDbfs)) {
    floor = Math.pow(10, knownNoiseFloorDbfs / 20);
  }
  const peakDb = dbfs(peak);
  const rmsDb = dbfs(rms);
  const floorDb = dbfs(floor);
  const snr = rms > 0 && floor > 0 ? Math.round(20 * Math.log10(rms / floor) * 100) / 100 : null;
  const clipRatio = clip / n;
  const flags: QualityFlag[] = [];
  if (peakDb === null || peakDb < THRESHOLDS.silentPeak) flags.push('silent');
  else {
    if (clipRatio > THRESHOLDS.clipRatio) flags.push('clipping');
    if (rmsDb !== null && rmsDb > THRESHOLDS.tooLoudRms) flags.push('too_loud');
    if (rmsDb !== null && rmsDb < THRESHOLDS.tooQuietRms) flags.push('too_quiet');
    if (snr !== null && snr < THRESHOLDS.minSnr) flags.push('noisy');
  }
  return {
    duration_s: Math.round((n / sampleRate) * 1000) / 1000,
    peak_dbfs: peakDb,
    rms_dbfs: rmsDb,
    noise_floor_dbfs: floorDb,
    snr_db: snr,
    clip_count: clip,
    clip_ratio: Math.round(clipRatio * 1e6) / 1e6,
    flags,
    ok: flags.length === 0,
  };
}

/** Goertzel power at one frequency, normalised per sample. Used by the headphone leak check. */
export function goertzelPower(samples: Int16Array | Float32Array, sampleRate: number, freq: number): number {
  const n = samples.length;
  if (n === 0) return 0;
  const k = Math.round((n * freq) / sampleRate);
  const w = (2 * Math.PI * k) / n;
  const coeff = 2 * Math.cos(w);
  let s0 = 0, s1 = 0, s2 = 0;
  const scale = samples instanceof Int16Array ? 1 / 32768 : 1;
  for (let i = 0; i < n; i++) {
    s0 = samples[i] * scale + coeff * s1 - s2;
    s2 = s1;
    s1 = s0;
  }
  const power = s1 * s1 + s2 * s2 - coeff * s1 * s2;
  return power / (n * n);
}

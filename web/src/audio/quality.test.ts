import { describe, expect, it } from 'vitest';
import { analyzeTake, goertzelPower, THRESHOLDS } from './quality';
import { evaluateLeak, LEAK_THRESHOLD_DB } from './headphones';

function sine(seconds: number, sr: number, freq: number, amp: number, noise = 0): Int16Array {
  const n = Math.floor(seconds * sr);
  const out = new Int16Array(n);
  let seed = 1;
  const rnd = () => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed / 0x7fffffff - 0.5; };
  for (let i = 0; i < n; i++) {
    const v = amp * Math.sin((2 * Math.PI * freq * i) / sr) + noise * rnd();
    out[i] = Math.max(-32768, Math.min(32767, Math.round(v * 32767)));
  }
  return out;
}

describe('analyzeTake', () => {
  it('reports a clean take as ok', () => {
    const q = analyzeTake(sine(1, 48000, 220, 0.3), 48000, -60);
    expect(q.ok).toBe(true);
    expect(q.duration_s).toBeCloseTo(1, 3);
    expect(q.rms_dbfs).toBeCloseTo(20 * Math.log10(0.3 / Math.SQRT2), 0);
    expect(q.clip_count).toBe(0);
    expect(q.snr_db).toBeGreaterThan(THRESHOLDS.minSnr);
  });

  it('flags clipping', () => {
    const q = analyzeTake(sine(1, 48000, 220, 1.2), 48000, -60);
    expect(q.flags).toContain('clipping');
    expect(q.ok).toBe(false);
  });

  it('flags too quiet and silence', () => {
    expect(analyzeTake(sine(1, 48000, 220, 0.005), 48000, -80).flags).toContain('too_quiet');
    expect(analyzeTake(new Int16Array(48000), 48000).flags).toEqual(['silent']);
    expect(analyzeTake(new Int16Array(0), 48000).flags).toEqual(['silent']);
  });

  it('flags a noisy take using the known noise floor', () => {
    const q = analyzeTake(sine(1, 48000, 220, 0.1), 48000, -25); // signal ≈ -23 dBFS, floor -25
    expect(q.flags).toContain('noisy');
  });

  it('estimates the noise floor from quiet windows when none is given', () => {
    const sr = 16000;
    const half = sine(0.5, sr, 220, 0.3);
    const quiet = sine(0.5, sr, 220, 0, 0.002);
    const both = new Int16Array(half.length + quiet.length);
    both.set(quiet);
    both.set(half, quiet.length);
    const q = analyzeTake(both, sr);
    expect(q.noise_floor_dbfs).toBeLessThan(-50);
    expect(q.snr_db).toBeGreaterThan(30);
  });
});

describe('goertzel + headphone leak', () => {
  it('finds tone energy at the right bin', () => {
    const tone = sine(1.2, 48000, 1000, 0.2);
    const other = sine(1.2, 48000, 300, 0.2);
    expect(goertzelPower(tone, 48000, 1000)).toBeGreaterThan(goertzelPower(other, 48000, 1000) * 1000);
  });

  it('detects speaker leak and passes headphones', () => {
    const silence = sine(1.2, 48000, 300, 0, 0.001);
    const leaking = sine(1.2, 48000, 1000, 0.05, 0.001); // -29 dBFS: speakers
    const r1 = evaluateLeak(leaking, silence, 48000);
    expect(r1.ok).toBe(false);
    expect(r1.leak_db).toBeGreaterThan(LEAK_THRESHOLD_DB);
    expect(r1.tone_dbfs).toBeGreaterThan(-32);
    const r2 = evaluateLeak(sine(1.2, 48000, 300, 0, 0.001), silence, 48000);
    expect(r2.ok).toBe(true);
    // Faint but measurable leak (-55 dBFS) is far above an empty bin yet inaudible: must pass.
    const faint = sine(1.2, 48000, 1000, 0.0025, 0.001);
    const r3 = evaluateLeak(faint, silence, 48000);
    expect(r3.leak_db).toBeGreaterThan(LEAK_THRESHOLD_DB);
    expect(r3.tone_dbfs).toBeLessThan(-45);
    expect(r3.ok).toBe(true);
  });
});

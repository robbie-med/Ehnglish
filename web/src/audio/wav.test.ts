import { describe, expect, it } from 'vitest';
import { encodeWav, float32ToInt16, parseWavHeader } from './wav';

describe('wav', () => {
  it('converts float to int16 with clipping', () => {
    const out = float32ToInt16([new Float32Array([0, 0.5, -0.5, 1.5, -1.5])]);
    expect(Array.from(out)).toEqual([0, 16384, -16384, 32767, -32768]);
  });

  it('round-trips a header', () => {
    const samples = new Int16Array(48000); // 1 s
    const buf = encodeWav(samples, 48000, 1);
    expect(buf.byteLength).toBe(44 + 96000);
    const h = parseWavHeader(buf);
    expect(h).toMatchObject({ sampleRate: 48000, channels: 1, bitsPerSample: 16, dataOffset: 44, dataBytes: 96000 });
    expect(h.durationS).toBeCloseTo(1, 6);
    expect(new TextDecoder().decode(new Uint8Array(buf, 0, 4))).toBe('RIFF');
  });

  it('rejects junk', () => {
    expect(() => parseWavHeader(new Uint8Array(50).buffer)).toThrow();
  });
});

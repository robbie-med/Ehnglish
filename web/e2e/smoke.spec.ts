/**
 * Records a fake audio take through the real recorder (AudioWorklet → WAV → chunked upload) and
 * verifies the server stored a valid WAV, then runs the worker once and checks the stub result.
 */
import { execFileSync } from 'node:child_process';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, test } from '@playwright/test';
import { API_PORT } from '../playwright.config';

const __dirname = dirname(fileURLToPath(import.meta.url));
const API = `http://127.0.0.1:${API_PORT}/api`;
const SERVER_DIR = resolve(__dirname, '../../server');

function parseWav(buf: Buffer) {
  expect(buf.subarray(0, 4).toString('ascii')).toBe('RIFF');
  expect(buf.subarray(8, 12).toString('ascii')).toBe('WAVE');
  let pos = 12;
  let fmt: { channels: number; sampleRate: number; bits: number } | null = null;
  while (pos + 8 <= buf.length) {
    const id = buf.subarray(pos, pos + 4).toString('ascii');
    const size = buf.readUInt32LE(pos + 4);
    if (id === 'fmt ') fmt = { channels: buf.readUInt16LE(pos + 10), sampleRate: buf.readUInt32LE(pos + 12), bits: buf.readUInt16LE(pos + 22) };
    if (id === 'data') {
      if (!fmt) throw new Error('data before fmt');
      expect(buf.length).toBe(pos + 8 + size);
      return { ...fmt, dataBytes: size, durationS: size / (fmt.channels * (fmt.bits / 8)) / fmt.sampleRate };
    }
    pos += 8 + size + (size & 1);
  }
  throw new Error('no data chunk');
}

test('dummy form end to end: record, upload, store, process', async ({ page, request }) => {
  await page.goto('/');
  await expect(page.getByTestId('who')).toHaveText('e2e@example.com');

  // Setup (C0) with the quick flag: 1 s silence instead of 10 s.
  await page.getByTestId('start-dummy-v0').click();
  await page.waitForURL(/\/setup\/dummy-v0/);
  await page.goto(page.url() + '?quick=1');
  await page.getByTestId('enable-mic').click();
  await expect(page.getByTestId('mic-select')).toBeVisible();
  await page.getByTestId('measure-noise').click();
  await expect(page.getByTestId('noise-result')).toBeVisible({ timeout: 15_000 });
  await page.getByTestId('headphone-check').click();
  await expect(page.getByTestId('headphone-result')).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId('headphone-result')).toHaveClass(/status-ok/);
  await page.getByTestId('sleep').fill('6.5');
  await page.getByTestId('stress').fill('4');
  await page.getByTestId('start-session').click();
  await page.waitForURL(/\/session\//);
  const sessionId = page.url().split('/session/')[1];

  // Task D1: two read-aloud items; re-record the first one once.
  await page.getByTestId('begin').click();
  await page.getByTestId('start-task').click();
  await expect(page.getByTestId('item-text')).toContainText('pharmacist');
  await expect(page.getByTestId('recording')).toBeVisible({ timeout: 10_000 });
  await expect(page.getByTestId('review')).toBeVisible({ timeout: 15_000 });
  await page.getByTestId('rerecord').click();
  await expect(page.getByTestId('review')).toBeVisible({ timeout: 20_000 });
  await page.getByTestId('accept').click();
  await expect(page.getByTestId('item-text')).toContainText('clinic');
  await expect(page.getByTestId('review')).toBeVisible({ timeout: 20_000 });
  await page.getByTestId('accept').click();

  // Task D2: typed response with keystrokes.
  await page.getByTestId('start-task').click();
  await expect(page.getByTestId('item-prompt')).toBeVisible();
  await page.getByTestId('typed-input').pressSequentially('Hi, I need to reschedule my appointment.', { delay: 20 });
  await page.getByTestId('done-typing').click();

  await page.waitForURL(/\/done\//);
  await expect(page.getByTestId('session-id')).toHaveText(sessionId);
  await expect(page.getByTestId('upload-state')).toHaveClass(/status-ok/, { timeout: 30_000 });

  // Verify on the server.
  const sres = await request.get(`${API}/sessions/${sessionId}`);
  expect(sres.ok()).toBeTruthy();
  const session = await sres.json();
  expect(session.status).toBe('done');
  expect(session.setup.sleep_h).toBe(6.5);
  expect(session.setup.noise_floor).toBeTruthy();
  expect(session.setup.headphones.ok).toBe(true);

  const takes = session.takes as Array<Record<string, any>>;
  const audio = takes.filter((t) => t.kind === 'audio');
  const typed = takes.filter((t) => t.kind === 'typed');
  expect(audio.map((t) => [t.item_id, t.attempt, t.status]).sort()).toEqual([
    ['D1-01', 1, 'rejected'], ['D1-01', 2, 'finalized'], ['D1-02', 1, 'finalized'],
  ]);
  expect(typed).toHaveLength(1);
  expect(typed[0].text).toContain('reschedule');
  expect(typed[0].keystroke_count).toBeGreaterThan(40);

  for (const t of audio.filter((t) => t.status === 'finalized')) {
    expect(t.duration_s).toBeGreaterThan(3.5);
    expect(t.duration_s).toBeLessThan(5);
    expect(t.quality.rms_dbfs).toBeLessThan(0);
    expect(t.events.map((e: { name: string }) => e.name)).toEqual(expect.arrayContaining(['prompt_end', 'record_start', 'record_stop', 'accepted']));
    const wav = Buffer.from(await (await request.get(`${API}/takes/${t.id}/audio`)).body());
    const h = parseWav(wav);
    expect(h.bits).toBe(16);
    expect(h.channels).toBe(1);
    expect(h.sampleRate).toBe(t.sample_rate);
    expect(Math.abs(h.durationS - t.duration_s)).toBeLessThan(0.01);
    // The fake device feeds real audio, so the file must not be digital silence.
    const pcm = new Int16Array(wav.buffer, wav.byteOffset + 44, h.dataBytes / 2);
    let peak = 0;
    for (const s of pcm) peak = Math.max(peak, Math.abs(s));
    expect(peak).toBeGreaterThan(1000);
  }

  // Run the worker once per queued job and check the stub result carries the pipeline version.
  execFileSync('uv', ['run', 'python', '-c',
    'from app.db import get_sessionmaker\nfrom app import worker\nwith get_sessionmaker()() as db:\n  n=0\n  while worker.run_once(db): n+=1\nprint("ran", n)'],
    { cwd: SERVER_DIR, env: { ...process.env, EHNGLISH_ENV: 'test', EHNGLISH_DATABASE_URL: 'postgresql+psycopg://ehnglish:ehnglish@127.0.0.1:3607/ehnglish', EHNGLISH_RAW_DIR: resolve(__dirname, '../../data/raw-e2e'), EHNGLISH_CONTENT_DIR: resolve(__dirname, '../../content'), EHNGLISH_PIPELINE_VERSION: 'e2e.0.1' }, stdio: 'pipe' });
  const after = await (await request.get(`${API}/sessions/${sessionId}`)).json();
  for (const t of (after.takes as Array<Record<string, any>>).filter((t) => t.kind === 'audio' && t.status !== 'rejected')) {
    expect(t.status).toBe('processed');
    expect(t.results[0].kind).toBe('wav_probe');
    expect(t.results[0].pipeline_version).toBe('e2e.0.1');
    expect(Math.abs(t.results[0].result.duration_s - t.duration_s)).toBeLessThan(0.01);
  }
});

/**
 * Every M1 task type end to end on the e2e-core form: silence, read-aloud (with review),
 * sentence repeat (audio prompt + beep), quick answer, describe/opinion (per-item prep) and a typed
 * item. Then the worker runs the M1 pipeline with no engine keys: every engine step must be
 * recorded as skipped, while the key-free steps (timing, latency, lexical, syntax) produce numbers.
 */
import { execFileSync } from 'node:child_process';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, test } from '@playwright/test';
import { API_PORT } from '../playwright.config';

const __dirname = dirname(fileURLToPath(import.meta.url));
const API = `http://127.0.0.1:${API_PORT}/api`;
const SERVER_DIR = resolve(__dirname, '../../server');
const ENV = {
  ...process.env,
  EHNGLISH_ENV: 'test',
  EHNGLISH_DATABASE_URL: 'postgresql+psycopg://ehnglish:ehnglish@127.0.0.1:3607/ehnglish',
  EHNGLISH_RAW_DIR: resolve(__dirname, '../../data/raw-e2e'),
  EHNGLISH_CONTENT_DIR: resolve(__dirname, '../../content'),
  EHNGLISH_PIPELINE_VERSION: 'e2e.0.1',
};

test('e2e-core form: every task type records, uploads and processes', async ({ page, request }) => {
  test.setTimeout(180_000);
  await page.goto('/');
  await page.getByTestId('start-e2e-core').click();
  await page.waitForURL(/\/setup\/e2e-core/);
  await page.goto(page.url() + '?quick=1');
  await page.getByTestId('enable-mic').click();
  await page.getByTestId('measure-noise').click();
  await expect(page.getByTestId('noise-result')).toBeVisible({ timeout: 15_000 });
  await page.getByTestId('headphone-check').click();
  await expect(page.getByTestId('headphone-result')).toHaveClass(/status-ok/, { timeout: 15_000 });
  await page.getByTestId('start-session').click();
  await page.waitForURL(/\/session\//);
  const sessionId = page.url().split('/session/')[1];

  await page.getByTestId('begin').click();
  // C0 silence: no review, auto-advances to the next task intro.
  await page.getByTestId('start-task').click();
  await expect(page.getByTestId('recording')).toBeVisible({ timeout: 10_000 });
  // C1 read aloud: review + accept.
  await page.getByTestId('start-task').click({ timeout: 15_000 });
  await expect(page.getByTestId('item-text')).toContainText('pharmacist');
  await expect(page.getByTestId('review')).toBeVisible({ timeout: 15_000 });
  await page.getByTestId('accept').click();
  // C2 sentence repeat: listening phase, then recording, no review.
  await page.getByTestId('start-task').click({ timeout: 15_000 });
  await expect(page.getByTestId('listening')).toBeVisible({ timeout: 10_000 });
  await expect(page.getByTestId('recording')).toBeVisible({ timeout: 10_000 });
  // C3 quick answer.
  await page.getByTestId('start-task').click({ timeout: 15_000 });
  await expect(page.getByTestId('listening')).toBeVisible({ timeout: 10_000 });
  await expect(page.getByTestId('recording')).toBeVisible({ timeout: 10_000 });
  // C5 describe + opinion: prep ("Think") then recording, twice.
  await page.getByTestId('start-task').click({ timeout: 15_000 });
  await expect(page.getByTestId('item-prompt')).toContainText('clinic');
  await expect(page.getByTestId('prep')).toBeVisible();
  await expect(page.getByTestId('recording')).toBeVisible({ timeout: 10_000 });
  await expect(page.getByTestId('item-prompt')).toContainText('email', { timeout: 15_000 });
  await expect(page.getByTestId('recording')).toBeVisible({ timeout: 10_000 });
  // W1 typed.
  await page.getByTestId('start-task').click({ timeout: 15_000 });
  await page.getByTestId('typed-input').pressSequentially('I called about my refill.', { delay: 10 });
  await page.getByTestId('done-typing').click();
  await page.waitForURL(/\/done\//);
  await expect(page.getByTestId('upload-state')).toHaveClass(/status-ok/, { timeout: 30_000 });

  const session = await (await request.get(`${API}/sessions/${sessionId}`)).json();
  const takes = session.takes as Array<Record<string, any>>;
  const byTask = (id: string) => takes.filter((t) => t.task_id === id && t.status !== 'rejected');
  expect(byTask('C0')).toHaveLength(1);
  expect(byTask('C1')).toHaveLength(1);
  expect(byTask('C2')[0].events.map((e: { name: string }) => e.name)).toEqual(
    expect.arrayContaining(['prompt_start', 'prompt_end', 'tone_end', 'record_start', 'record_stop']),
  );
  expect(byTask('C3')).toHaveLength(1);
  expect(byTask('C5')).toHaveLength(2);
  expect(byTask('W1')[0].text).toContain('refill');
  for (const t of takes.filter((t) => t.kind === 'audio' && t.status !== 'rejected')) {
    expect(t.status).toBe('finalized');
    expect(t.duration_s).toBeGreaterThan(0.8);
  }

  // Run the worker to completion (wav_probe + process_take per audio take).
  execFileSync('uv', ['run', 'python', '-c',
    'from app.db import get_sessionmaker\nfrom app import worker\nwith get_sessionmaker()() as db:\n  n=0\n  while worker.run_once(db): n+=1\nprint("ran", n)'],
    { cwd: SERVER_DIR, env: ENV, stdio: 'pipe' });
  const after = await (await request.get(`${API}/sessions/${sessionId}`)).json();
  const kinds = (t: Record<string, any>) => Object.fromEntries(t.results.map((r: any) => [r.kind, r.result]));
  for (const t of (after.takes as Array<Record<string, any>>).filter((t) => t.kind === 'audio' && t.status !== 'rejected')) {
    expect(t.status).toBe('processed');
    const k = kinds(t);
    expect(k.wav_probe.duration_s).toBeGreaterThan(0.8);
    if (t.task_id === 'C0') continue;
    expect(k['asr:deepgram'].skipped).toBe(true);
    expect(k.transcript.n_engines).toBe(0);
    expect(k.timing.duration_s).toBeGreaterThan(0.8);
    expect(t.results.every((r: any) => r.pipeline_version === 'e2e.0.1')).toBe(true);
    if (t.task_id === 'C2') expect(k.ei.target_syllables).toBe(8);
    if (t.task_id === 'C3') expect(k.latency).toBeTruthy();
    if (t.task_id === 'C5') expect(k.lexical.tokens).toBe(0);
    if (t.task_id === 'C1') expect(k.pron.skipped).toBe(true);
  }
});

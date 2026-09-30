import { defineConfig, devices } from '@playwright/test';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));

// Smoke test: needs the throwaway Postgres (deploy/docker-compose.test.yml) running on 3607.
const root = resolve(__dirname, '..');
const fixture = resolve(__dirname, 'e2e/fixtures/speech.wav');
export const API_PORT = '3915'; // registered as ehnglish-api-e2e; prod api owns 3305
const serverEnv = {
  EHNGLISH_ENV: 'test',
  EHNGLISH_DEV_EMAIL: 'e2e@example.com',
  EHNGLISH_DATABASE_URL: 'postgresql+psycopg://ehnglish:ehnglish@127.0.0.1:3607/ehnglish',
  EHNGLISH_RAW_DIR: resolve(root, 'data/raw-e2e'),
  EHNGLISH_CONTENT_DIR: resolve(root, 'content'),
  EHNGLISH_PIPELINE_VERSION: 'e2e.0.1',
};

export default defineConfig({
  testDir: './e2e',
  timeout: 90_000,
  retries: 0,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: 'http://127.0.0.1:3914',
    trace: 'retain-on-failure',
    permissions: ['microphone'],
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        launchOptions: {
          args: [
            '--use-fake-device-for-media-stream',
            '--use-fake-ui-for-media-stream',
            `--use-file-for-fake-audio-capture=${fixture}`,
            '--autoplay-policy=no-user-gesture-required',
          ],
        },
      },
    },
  ],
  webServer: [
    {
      command: `uv run alembic upgrade head && uv run uvicorn app.main:app --host 127.0.0.1 --port ${API_PORT}`,
      cwd: resolve(root, 'server'),
      url: `http://127.0.0.1:${API_PORT}/api/health`,
      env: serverEnv,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: 'npm run dev',
      cwd: __dirname,
      env: { EHNGLISH_API_PORT: API_PORT },
      url: 'http://127.0.0.1:3914',
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
});

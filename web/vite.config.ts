/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { VitePWA } from 'vite-plugin-pwa';
import { readFileSync } from 'node:fs';
import { execSync } from 'node:child_process';

const pkg = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8')) as { version: string };
let sha = 'dev';
try { sha = execSync('git rev-parse --short HEAD', { stdio: ['ignore', 'pipe', 'ignore'] }).toString().trim(); } catch { /* no git in the image */ }
// Unique per build: Safari only swaps service workers when the file really changes.
const BUILD_ID = `${pkg.version}+${sha}.${Date.now().toString(36)}`;

// Ports are registered in /home/user/Projects/PORTS.md: 3914 = ehnglish-vite, 3305 = ehnglish-api,
// 3915 = ehnglish-api-e2e (EHNGLISH_API_PORT under Playwright).
export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      injectRegister: false,
      includeAssets: ['worklet/pcm-recorder.js'],
      manifest: {
        name: 'Ehnglish assessment · 영어 평가',
        short_name: 'Ehnglish',
        description: 'Private monthly English assessment. 개인 월간 영어 평가.',
        theme_color: '#f3eee4',
        background_color: '#f3eee4',
        display: 'standalone',
        lang: 'en',
        icons: [{ src: 'icon.svg', sizes: 'any', type: 'image/svg+xml', purpose: 'any' }],
      },
      workbox: {
        skipWaiting: true,
        clientsClaim: true,
        cleanupOutdatedCaches: true,
        // Never cache API calls or audio; the upload queue handles offline.
        navigateFallbackDenylist: [/^\/api\//],
        additionalManifestEntries: [{ url: '/__build', revision: BUILD_ID }],
        runtimeCaching: [
          { urlPattern: /^\/api\//, handler: 'NetworkOnly' },
          { urlPattern: /^https:\/\/fonts\.(googleapis|gstatic)\.com\//, handler: 'CacheFirst', options: { cacheName: 'fonts', expiration: { maxEntries: 20, maxAgeSeconds: 60 * 60 * 24 * 365 } } },
        ],
      },
    }),
  ],
  define: { __APP_VERSION__: JSON.stringify(pkg.version), __BUILD_ID__: JSON.stringify(BUILD_ID) },
  server: {
    host: '127.0.0.1',
    port: 3914,
    strictPort: true,
    proxy: { '/api': { target: `http://127.0.0.1:${process.env.EHNGLISH_API_PORT ?? '3305'}`, changeOrigin: false } },
  },
  preview: { host: '127.0.0.1', port: 3914, strictPort: true },
  test: {
    include: ['src/**/*.test.ts'],
    environment: 'node',
  },
});

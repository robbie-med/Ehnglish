/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { VitePWA } from 'vite-plugin-pwa';
import { readFileSync } from 'node:fs';

const pkg = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8')) as { version: string };

// Ports are registered in /home/user/Projects/PORTS.md: 3914 = ehnglish-vite, 3305 = ehnglish-api,
// 3915 = ehnglish-api-e2e (EHNGLISH_API_PORT under Playwright).
export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['worklet/pcm-recorder.js'],
      manifest: {
        name: 'Ehnglish assessment · 영어 평가',
        short_name: 'Ehnglish',
        description: 'Private monthly English assessment. 개인 월간 영어 평가.',
        theme_color: '#1d4ed8',
        background_color: '#fafafa',
        display: 'standalone',
        lang: 'en',
        icons: [{ src: 'icon.svg', sizes: 'any', type: 'image/svg+xml', purpose: 'any' }],
      },
      workbox: {
        // Never cache API calls or audio; the upload queue handles offline.
        navigateFallbackDenylist: [/^\/api\//],
        runtimeCaching: [{ urlPattern: /^\/api\//, handler: 'NetworkOnly' }],
      },
    }),
  ],
  define: { __APP_VERSION__: JSON.stringify(pkg.version) },
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

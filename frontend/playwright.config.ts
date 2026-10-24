import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { defineConfig } from '@playwright/test';

/**
 * The browser smoke suite (`e2e/`). `scripts/e2e.sh` builds the SPA, boots PREVIEW_MODE backends
 * that serve it and runs this; to run it against a backend you started yourself, set
 * E2E_BASE_URL (and E2E_ZERO_KEY_URL for the zero-key spec). Reports and traces go outside the
 * repo unless E2E_ARTIFACTS says where.
 */
const artifacts = process.env.E2E_ARTIFACTS ?? join(tmpdir(), 'springform-e2e');

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  expect: { timeout: 10_000 },
  retries: 1,
  forbidOnly: !!process.env.CI,
  reporter: [['list'], ['html', { outputFolder: join(artifacts, 'report'), open: 'never' }]],
  outputDir: join(artifacts, 'results'),
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://127.0.0.1:8160',
    browserName: 'chromium',
    trace: 'on-first-retry',
  },
  projects: [
    { name: 'desktop', use: { viewport: { width: 1280, height: 800 } } },
    // Install-wide state, so desktop only: a frozen clock gives every backup the same stamp, and
    // hiding an app would race the same test at the other width.
    {
      name: 'mobile', testIgnore: /(backups|hidden-app)\.spec\.ts/,
      use: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true },
    },
  ],
});

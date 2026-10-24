import { readFileSync } from 'node:fs'
import { defineConfig } from 'vitest/config'
import springformApps from './vite-plugin-apps'

/**
 * A standalone config rather than a `test` block in `vite.config.ts`, so tests skip the React
 * and Tailwind plugins and never inherit the dev proxy. It does NOT inherit `vite.config.ts`'s
 * plugins either, which is why the apps plugin is listed again here.
 *
 * Test-runner options MUST stay under `test` (vitest ignores them at the top level), and
 * Vite-level keys such as `define` MUST stay at the top level.
 */
export default defineConfig({
  plugins: [springformApps()],
  // The shipped stylesheet's text, for the contrast guards in `src/core/theme/`. `?raw` CSS
  // imports are stubbed to '' under vitest, and `node:fs` in a src test would need Node types
  // in the app tsconfig, so the text is injected here.
  define: {
    __INDEX_CSS__: JSON.stringify(readFileSync(new URL('./src/index.css', import.meta.url), 'utf8')),
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
    include: ['src/**/*.test.{ts,tsx}', '*.test.ts'],
    // Fail closed: "0 tests, exit 0" and assertion-free tests must not read as green.
    passWithNoTests: false,
    allowOnly: false,
    expect: { requireAssertions: true },
    // Not UTC on purpose: a UTC runner hides local-vs-UTC date bugs.
    env: { TZ: 'America/Chicago' },
  },
})

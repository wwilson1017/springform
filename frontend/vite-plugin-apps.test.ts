// @vitest-environment node
import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import springformApps, { readManifests } from './vite-plugin-apps';

function fixture(apps: Record<string, string | null>): string {
  const dir = mkdtempSync(join(tmpdir(), 'sf-apps-'));
  for (const [slug, json] of Object.entries(apps)) {
    mkdirSync(join(dir, slug));
    if (json !== null) writeFileSync(join(dir, slug, 'app.json'), json);
  }
  return dir;
}

describe('vite-plugin-apps', () => {
  it('reads every app.json, sorted by order then slug, skipping folders without one', () => {
    const dir = fixture({
      zeta: '{"slug":"zeta","order":10}',
      alpha: '{"slug":"alpha","order":10}',
      first: '{"slug":"first","order":5}',
      notes: null,
    });
    expect(readManifests(dir).map((m) => m.slug)).toEqual(['first', 'alpha', 'zeta']);
  });

  it('serves the list as the virtual module', () => {
    const plugin = springformApps({ appsDir: fixture({ one: '{"slug":"one","order":1}' }) });
    const resolveId = plugin.resolveId as (id: string) => string | undefined;
    const load = plugin.load as (id: string) => string | undefined;
    const id = resolveId('virtual:springform-apps')!;
    expect(load(id)).toBe('export default [{"slug":"one","order":1}];');
    expect(resolveId('./other')).toBeUndefined();
  });

  it('fails loudly on a broken manifest or a missing apps directory', () => {
    expect(() => readManifests(fixture({ bad: '{nope' }))).toThrow(/bad.app\.json/);
    expect(() => readManifests('/nonexistent/apps')).toThrow(/no apps directory/);
  });

  it('reads the real backend/apps by default', () => {
    const plugin = springformApps();
    const load = plugin.load as (id: string) => string;
    expect(load('\0virtual:springform-apps')).toContain('"slug":"example"');
  });
});

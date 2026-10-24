/**
 * The frontend half of the app contract (the backend half is tests/test_app_contract.py):
 * every manifest has `contributions.ts` + `index.tsx` and vice versa, the slugs agree, every
 * settings card has exactly one loader, and no app reaches into another app's folder.
 */
import manifests from 'virtual:springform-apps';
import { describe, expect, it } from 'vitest';
import type { AppContributions, AppModule } from './types';
import { appBySlug, navItems, recordPanelsFor, settingsCardsFor } from './registry';

const contributions = import.meta.glob<AppContributions>('../../apps/*/contributions.ts', { eager: true, import: 'default' });
const screens = import.meta.glob<AppModule>('../../apps/*/index.tsx', { import: 'default' });
const sources = import.meta.glob<string>('../../apps/**/*.{ts,tsx}', { query: '?raw', import: 'default', eager: true });

/** '../../apps/<slug>/…' -> '<slug>' */
const slugOf = (path: string) => path.split('/')[3];
const manifestSlugs = manifests.map(m => m.slug).sort();

/**
 * Every import specifier in a source (static, re-export, side-effect and dynamic) that resolves
 * into ANOTHER app's folder. `file` is '../../apps/<slug>/<path>'.
 */
function crossAppImports(file: string, source: string): string[] {
  const own = slugOf(file);
  const specs = [...source.matchAll(/(?:\bfrom\s*|\bimport\s*\(?\s*)['"]([^'"]+)['"]/g)].map(m => m[1]);
  return specs.filter(spec => {
    if (!spec.startsWith('.')) return false;
    const parts = file.split('/').slice(0, -1);
    for (const seg of spec.split('/')) {
      if (seg === '..') parts.pop();
      else if (seg !== '.') parts.push(seg);
    }
    // parts is now e.g. ['..', '..', 'apps', '<slug>', ...] relative to src/core/apps.
    return parts[2] === 'apps' && parts.length > 3 && parts[3] !== own;
  });
}

describe('app contract', () => {
  it('finds the installed apps', () => {
    expect(manifestSlugs).toContain('example');
  });

  it('every manifest has contributions.ts and index.tsx, and every app folder a manifest', () => {
    expect(Object.keys(contributions).map(slugOf).sort()).toEqual(manifestSlugs);
    expect(Object.keys(screens).map(slugOf).sort()).toEqual(manifestSlugs);
  });

  it('contributions and index.tsx name the same slug as their folder', async () => {
    for (const [path, c] of Object.entries(contributions)) expect(c.slug, path).toBe(slugOf(path));
    for (const [path, load] of Object.entries(screens)) {
      const mod = await load();
      expect(mod.slug, path).toBe(slugOf(path));
      expect(typeof mod.App, `${path} must default-export { slug, App }`).toBe('function');
    }
  });

  it('every settings_cards[].id has exactly one loader, and every loader a manifest card', () => {
    for (const m of manifests) {
      const ids = (m.settings_cards ?? []).map(c => c.id).sort();
      const loaders = Object.keys(contributions[`../../apps/${m.slug}/contributions.ts`]?.settingsCards ?? {}).sort();
      expect(loaders, `${m.slug} settings card loaders`).toEqual(ids);
    }
  });

  it('no app imports from another app folder', () => {
    const violations = Object.entries(sources).flatMap(([file, src]) => crossAppImports(file, src).map(s => `${file}: ${s}`));
    expect(violations).toEqual([]);
  });

  it('the cross-app scanner catches every import shape and ignores own-folder and core imports', () => {
    const file = '../../apps/crm/pages/Deals.tsx';
    expect(crossAppImports(file, [
      "import { x } from '../../todos/api';",
      "export { y } from \"../../todos/api\";",
      "import '../../todos/side-effect';",
      "const P = lazy(() => import('../../todos/Page'));",
    ].join('\n'))).toHaveLength(4);
    expect(crossAppImports(file, [
      "import { a } from '../api';",
      "import { b } from '../../../core/api/client';",
      "import { c } from 'react';",
    ].join('\n'))).toEqual([]);
  });

  it('the registry wires the example app into every seam', () => {
    expect(appBySlug('example')?.manifest.path).toBe('/example');
    expect(settingsCardsFor('example').map(c => c.id)).toEqual(['example']);
    expect(recordPanelsFor('core.person').map(p => p.slug)).toContain('example');
    expect(navItems().find(n => n.slug === 'example')).toMatchObject({ to: '/example', icon: 'flask' });
  });
});

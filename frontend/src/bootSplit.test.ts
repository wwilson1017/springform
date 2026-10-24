// @vitest-environment node
//
// The boot split: the shell is eager, every app's screens are lazy. Two halves, because each
// misses what the other catches:
//   - SOURCE: `contributions.ts` is pulled EAGERLY into the shell by the registry, so it may hold
//     lazy loaders and data only (no value import) and stays tiny.
//   - BUILD: build the real app in memory and walk the chunk graph. A static import of an app
//     module from anywhere in the shell, however indirect, shows up here as an app module in the
//     entry chunk's download, even when every source file looks right.
import { build } from 'vite';
import { describe, expect, it } from 'vitest';

const contributionSources = import.meta.glob<string>('./apps/*/contributions.ts', { query: '?raw', import: 'default', eager: true });

/** Value imports and re-exports; `import type` / `export type` are erased and allowed. */
const valueImports = (source: string) =>
  [...source.matchAll(/^\s*(?:import|export)\s+(?!type\b)[^;]*?\bfrom\s*['"][^'"]+['"]|^\s*import\s*['"][^'"]+['"]/gm)].map(m => m[0].trim());

describe('boot split: source', () => {
  it('finds the apps', () => {
    expect(Object.keys(contributionSources).length).toBeGreaterThan(0);
  });

  it('contributions.ts has no value imports and stays under 2 KB', () => {
    for (const [file, source] of Object.entries(contributionSources)) {
      expect(valueImports(source), `${file} must only lazy-load (() => import(...))`).toEqual([]);
      expect(new TextEncoder().encode(source).length, `${file} size`).toBeLessThan(2048);
    }
  });

  it('the value-import detector is falsifiable', () => {
    expect(valueImports("import { Page } from './Page';\nexport { x } from './x';\nimport './side';")).toHaveLength(3);
    expect(valueImports("import type { A } from './a';\nconst p = () => import('./Page');")).toEqual([]);
  });
});

type Chunk = { fileName: string; isEntry: boolean; facadeModuleId: string | null; modules: Record<string, unknown>; imports: string[] };

const ROOT = new URL('..', import.meta.url).pathname;
const rel = (id: string) => (id.startsWith(ROOT) ? id.slice(ROOT.length) : id).replace(/^\/+/, '');

async function buildChunks(): Promise<Chunk[]> {
  // vitest sets NODE_ENV=test, which hands the React plugin its dev JSX runtime; build what ships.
  const previous = process.env.NODE_ENV;
  process.env.NODE_ENV = 'production';
  try {
    const result = await build({ root: ROOT, mode: 'production', logLevel: 'silent', build: { write: false } });
    const bundle = Array.isArray(result) ? result[0] : result;
    if (!bundle || !('output' in bundle)) throw new Error('vite build returned a watcher, not a bundle');
    return (bundle.output as unknown as Array<Chunk & { type: string }>).filter(o => o.type === 'chunk');
  } finally {
    process.env.NODE_ENV = previous;
  }
}

describe('boot split: built chunk graph', async () => {
  const chunks = await buildChunks();
  const byFile = new Map(chunks.map(c => [c.fileName, c]));
  const entries = chunks.filter(c => c.isEntry);

  /** Source modules a chunk downloads: itself plus its static imports, transitively. */
  function downloadedBy(start: Chunk): Set<string> {
    const seen = new Set<string>();
    const modules = new Set<string>();
    const stack = [start.fileName];
    while (stack.length) {
      const name = stack.pop()!;
      if (seen.has(name)) continue;
      seen.add(name);
      const chunk = byFile.get(name);
      if (!chunk) throw new Error(`chunk '${name}' is imported but not emitted`);
      Object.keys(chunk.modules).forEach(id => modules.add(rel(id)));
      stack.push(...chunk.imports);
    }
    return modules;
  }

  it('has one entry, and its download includes the shell and React', () => {
    expect(entries).toHaveLength(1);
    const entry = downloadedBy(entries[0]);
    expect(entry.has('src/core/Root.tsx')).toBe(true);
    expect([...entry].some(m => m.includes('node_modules/react-dom'))).toBe(true);
  });

  it('the entry downloads no app module except contributions.ts', () => {
    const appModules = [...downloadedBy(entries[0])].filter(m => m.startsWith('src/apps/'));
    expect(appModules.filter(m => !/^src\/apps\/[^/]+\/contributions\.ts$/.test(m))).toEqual([]);
    expect(appModules.length, 'the registry pulls each contributions.ts in eagerly').toBeGreaterThan(0);
  });

  it("every app's index.tsx is its own lazy chunk", () => {
    for (const slug of Object.keys(contributionSources).map(p => p.split('/')[2])) {
      const chunk = chunks.find(c => c.facadeModuleId && rel(c.facadeModuleId) === `src/apps/${slug}/index.tsx`);
      expect(chunk, `src/apps/${slug}/index.tsx is not a code-split boundary`).toBeDefined();
      expect(chunk!.isEntry).toBe(false);
    }
  });
});

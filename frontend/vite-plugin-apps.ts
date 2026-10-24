import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { join, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import type { Plugin } from 'vite';

/**
 * `virtual:springform-apps`: every `backend/apps/<slug>/app.json`, parsed and sorted by `order`
 * then slug. The manifest is the one source of truth for an app's name, path, icon and settings
 * cards, so the frontend reads it at build time rather than keeping a second copy.
 *
 * The build therefore needs `backend/apps/*\/app.json` next to `frontend/` (a Docker frontend
 * stage must copy them). A missing apps directory throws instead of shipping an empty launcher.
 *
 * `appsDir` is the injection point for tests: point it at a fixture directory.
 */

const ID = 'virtual:springform-apps';
const RESOLVED = '\0' + ID;

type Manifest = { slug: string; order: number };

export function readManifests(appsDir: string): Manifest[] {
  if (!existsSync(appsDir)) throw new Error(`springform-apps: no apps directory at ${appsDir}`);
  return readdirSync(appsDir, { withFileTypes: true })
    .filter((d) => d.isDirectory() && existsSync(join(appsDir, d.name, 'app.json')))
    .map((d) => {
      const file = join(appsDir, d.name, 'app.json');
      try {
        return JSON.parse(readFileSync(file, 'utf8')) as Manifest;
      } catch (e) {
        throw new Error(`springform-apps: ${file}: ${(e as Error).message}`);
      }
    })
    .sort((a, b) => a.order - b.order || (a.slug < b.slug ? -1 : a.slug > b.slug ? 1 : 0));
}

export default function springformApps({
  appsDir = fileURLToPath(new URL('../backend/apps', import.meta.url)),
}: { appsDir?: string } = {}): Plugin {
  return {
    name: 'springform-apps',
    resolveId: (id) => (id === ID ? RESOLVED : undefined),
    load(id) {
      if (id !== RESOLVED) return;
      return `export default ${JSON.stringify(readManifests(appsDir))};`;
    },
    // HMR: the apps directory sits outside Vite's root, so watch it by hand. A manifest change
    // can add or remove routes, so the page reloads rather than hot-swapping.
    configureServer(server) {
      server.watcher.add(appsDir);
      const onFile = (file: string) => {
        if (!file.startsWith(appsDir) || !file.endsWith(`${sep}app.json`)) return;
        const mod = server.moduleGraph.getModuleById(RESOLVED);
        if (mod) server.moduleGraph.invalidateModule(mod);
        server.ws.send({ type: 'full-reload' });
      };
      server.watcher.on('add', onFile).on('change', onFile).on('unlink', onFile);
    },
  };
}

// @vitest-environment node
// A response shape the backend declares is an alias of its generated schema (`api/types.gen.ts`),
// never a hand-written copy: a copy keeps compiling after the backend changes and drifts silently.
// This fails when a core `types.ts` declares an interface, or an object type literal, under a
// generated schema's name.
import { describe, expect, it } from 'vitest';
import generated from './api/types.gen.ts?raw';

const typeFiles = import.meta.glob<string>('./**/types.ts', { query: '?raw', import: 'default', eager: true });

/** The keys of `components.schemas` in the generated file. */
function schemaNames(source: string): Set<string> {
  const start = source.indexOf('\n    schemas: {');
  const block = source.slice(start, source.indexOf('\n    responses:', start));
  return new Set([...block.matchAll(/^ {8}(\w+): /gm)].map(m => m[1]));
}

const DECLARED = /^\s*(?:export\s+)?(?:interface\s+(\w+)|type\s+(\w+)(?:<[^=]*>)?\s*=\s*\{)/gm;

function twins(files: Record<string, string>, names: Set<string>): string[] {
  return Object.entries(files).flatMap(([file, text]) =>
    [...text.matchAll(DECLARED)].map(m => m[1] ?? m[2]).filter(n => names.has(n)).map(n => `${file}: ${n}`));
}

describe('generated type twins', () => {
  const names = schemaNames(generated);

  it('reached the real types and schemas', () => {
    expect(Object.keys(typeFiles)).toEqual(expect.arrayContaining(['./contacts/types.ts', './api/types.ts']));
    expect(names.has('PersonRow') && names.has('TimelineEntry')).toBe(true);
    expect(names.size).toBeGreaterThan(100);
  });

  it('no core types.ts hand-writes a shape the backend generates', () => {
    expect(twins(typeFiles, names)).toEqual([]);
  });

  it('is falsifiable', () => {
    const fake = new Set(['Workspace', 'KeyReveal']);
    expect(twins({
      'a/types.ts': 'export interface Workspace {\n  name: string;\n}',
      'b/types.ts': "export type KeyReveal = { key: string } | { fingerprint: string };",
    }, fake)).toEqual(['a/types.ts: Workspace', 'b/types.ts: KeyReveal']);
    expect(twins({
      'c/types.ts': "export type Workspace = S['Workspace'];\nexport interface ServerDraft {\n  name: string;\n}",
    }, fake)).toEqual([]);
  });
});

// @vitest-environment node
// Admins can rename the assistant, so the UI never spells its default name: every string reads
// `useAgentName()` (or the agentName prop), and only `DEFAULT_AGENT_NAME` holds the word. This
// fails on a "Whisk" in frontend/src outside that file, tests and comments. Identifiers such as
// WhiskPage and the `/whisk` route are not words on screen, so they pass.
import { describe, expect, it } from 'vitest';

const DEFAULT_FILE = './core/agent/useAgentName.ts';
const files = import.meta.glob<string>(['./**/*.{ts,tsx}', '!./**/*.test.{ts,tsx}', '!./**/*.testutil.ts'], {
  query: '?raw',
  import: 'default',
  eager: true,
});

const COMMENTS = /\/\*[\s\S]*?\*\/|(^|\s)\/\/.*$/gm;
const NAME = /\bWhisk\b/;

function offenders(sources: Record<string, string>): string[] {
  return Object.entries(sources)
    .filter(([file]) => file !== DEFAULT_FILE)
    .flatMap(([file, text]) =>
      text
        .replace(COMMENTS, '$1')
        .split('\n')
        .flatMap((line, i) => (NAME.test(line) ? [`${file}:${i + 1}: ${line.trim()}`] : [])),
    );
}

describe('the assistant name guard', () => {
  it('reached the real code', () => {
    expect(Object.keys(files)).toEqual(expect.arrayContaining([DEFAULT_FILE, './core/agent/WhiskPage.tsx']));
    expect(NAME.test(files[DEFAULT_FILE])).toBe(true);
  });

  it('no file outside the default constant spells the default name', () => {
    expect(offenders(files)).toEqual([]);
  });

  it('is falsifiable', () => {
    expect(
      offenders({
        'a.tsx': '<h2>Whisk needs an AI key</h2>',
        'b.ts': "const notice = 'Ask Whisk';",
      }),
    ).toEqual(['a.tsx:1: <h2>Whisk needs an AI key</h2>', "b.ts:1: const notice = 'Ask Whisk';"]);
    expect(
      offenders({
        'c.tsx': "/** Whisk's page */\nimport WhiskPage from './WhiskPage'; // Whisk\nconst to = '/whisk';",
        [DEFAULT_FILE]: "export const DEFAULT_AGENT_NAME = 'Whisk';",
      }),
    ).toEqual([]);
  });
});

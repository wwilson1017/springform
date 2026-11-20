import { describe, expect, it } from 'vitest';
import {
  AA_NORMAL_TEXT,
  CSS,
  DARK_TOKENS,
  LIGHT_TOKENS,
  contrast,
  hexToRgb,
  over,
  palette,
  resolve,
  themeTokens,
} from './palette.testutil';

/**
 * A fork's `public/branding/theme.css` over `src/index.css` (docs/agents/forks.md). The cascade
 * itself is proven in a real browser by e2e/branding.spec.ts; this pins the model the contrast
 * guards use and checks the header bar a fork colours.
 */

const FORK = `
/* a fork's file */
:root {
  --color-sf-accent: #1f6f78;
  --color-sf-accent-text: #1f6f78;
  --color-sf-header: #23313a;
}
:root.dark {
  --color-sf-accent-text: #7cc4cc;
}
`;

describe('fork theme override', () => {
  const upstream = palette(CSS, '');
  const fork = palette(CSS, FORK);

  it('leaves the upstream palette alone when theme.css sets nothing', () => {
    expect(resolve(upstream.light, 'accent')).toBe('#b5542d');
    expect(resolve(upstream.dark, 'accent-text')).toBe('#e4916a');
    expect(palette(CSS, '/* comments only */')).toEqual(upstream);
  });

  it('changes the accent in light and dark, and only what it sets', () => {
    expect(resolve(fork.light, 'accent')).toBe('#1f6f78');
    expect(resolve(fork.dark, 'accent')).toBe('#1f6f78');
    expect(resolve(fork.light, 'accent-text')).toBe('#1f6f78');
    expect(resolve(fork.dark, 'accent-text')).toBe('#7cc4cc');
    // :root applies in dark too, beating index.css's .dark block.
    expect(fork.dark.header).toBe('#23313a');
    expect(resolve(fork.dark, 'bg')).toBe(resolve(upstream.dark, 'bg'));
    expect(resolve(fork.light, 'ink')).toBe(resolve(upstream.light, 'ink'));
  });

  it('reads a last declaration with no semicolon, as the browser does', () => {
    expect(themeTokens(':root { --color-sf-accent: #000000 }').root.accent).toBe('#000000');
  });

  it('refuses rules that are not token blocks', () => {
    expect(() => themeTokens(':root { --color-sf-accent: #000000; }')).not.toThrow();
    expect(() => themeTokens('.dark { --color-sf-accent: #000000; }')).toThrow(/only :root/);
    expect(() => themeTokens('header { background: red; }')).toThrow(/only :root/);
  });
});

/** The bar's colours as the browser resolves index.css's var() fallbacks (see "Header bar" there). */
function bar(tokens: Record<string, string>) {
  const pick = (fork: string, page: string) => hexToRgb(resolve(tokens, tokens[fork] ? fork : page));
  const bg = pick('header', 'bg');
  const ink = pick('header-ink', 'ink');
  // header-ink set: the muted steps are an 80% mix of it; unset: today's ink-soft and ink-mute.
  const muted = tokens['header-ink']
    ? [over(ink, 80, bg)]
    : [hexToRgb(resolve(tokens, 'ink-soft')), hexToRgb(resolve(tokens, 'ink-mute'))];
  return { bg, text: [ink, ...muted] };
}

const passes = (tokens: Record<string, string>) => {
  const { bg, text } = bar(tokens);
  return text.every((fg) => contrast(fg, bg) >= AA_NORMAL_TEXT);
};

it('the header guard flags a low-contrast bar and passes a legible one', () => {
  const faint = palette(CSS, ':root { --color-sf-header: #23313a; --color-sf-header-ink: #4a5a66; }');
  const legible = palette(CSS, ':root { --color-sf-header: #23313a; --color-sf-header-ink: #ffffff; }');
  expect(passes(faint.light)).toBe(false);
  expect(passes(legible.light)).toBe(true);
  expect(passes(legible.dark)).toBe(true);
});

describe.each([
  ['light', LIGHT_TOKENS],
  ['dark', DARK_TOKENS],
])('%s header bar', (_theme, tokens) => {
  it('clears WCAG AA 4.5:1 for its text and icons', () => {
    expect(passes(tokens)).toBe(true);
  });
});

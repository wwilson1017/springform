import { describe, expect, it } from 'vitest';
import {
  AA_NORMAL_TEXT, BASES, CSS, DARK_TOKENS, LIGHT_TOKENS, contrast, hexToRgb, luminance, over, resolve, type Rgb,
} from './palette.testutil';

/**
 * WCAG AA guard for the status hues and the accent used as TEXT. Every hue is a FILL token and a
 * `-text` token (see index.css). The wash under a glyph is mixed from the FILL, which does not
 * move when the text token is retuned, so surfaces composite `tokens[hue]` while the ratio is
 * taken against `tokens[hue-text]`.
 *
 * Washes modelled (`tint(<hue>, N)` carrying its own glyph): every hue at 12% (the standard chip),
 * red also at 6% (`LoadError`'s panel), plus `LoadError`'s amber Retry on that red 6% panel.
 */

const HUES = ['green', 'amber', 'red', 'ai'] as const;
const OWN_WASH_PCTS: Record<string, number[]> = { red: [6, 12], amber: [12], green: [12], ai: [12] };

function surfaces(hue: string, tokens: Record<string, string>): Record<string, Rgb> {
  const rgb = (k: string) => hexToRgb(resolve(tokens, k));
  const out: Record<string, Rgb> = {};
  for (const base of BASES) {
    out[base] = rgb(base);
    for (const pct of OWN_WASH_PCTS[hue]) out[`own${pct}/${base}`] = over(rgb(hue), pct, rgb(base));
    if (hue === 'amber') out[`red6/${base}`] = over(rgb('red'), 6, rgb(base));
  }
  return out;
}

/** `--color-sf-accent-soft`'s mix percentage, which must be mixed from the accent FILL. */
function accentSoftPercent(tokens: Record<string, string>): number {
  const raw = tokens['accent-soft'] ?? '';
  const m = /^color-mix\(\s*in\s+srgb\s*,\s*var\(\s*--color-sf-accent\s*\)\s*([\d.]+)%\s*,\s*transparent\s*\)$/.exec(raw);
  if (!m) throw new Error(`index.css: could not read --color-sf-accent-soft as a mix of --color-sf-accent (got ${raw})`);
  return Number(m[1]);
}

const worstFor = (hue: string, tokens: Record<string, string>) => {
  const fg = hexToRgb(resolve(tokens, `${hue}-text`));
  return Math.min(...Object.values(surfaces(hue, tokens)).map((bg) => contrast(fg, bg)));
};

describe.each([
  ['light', LIGHT_TOKENS],
  ['dark', DARK_TOKENS],
])('%s theme hue-as-text', (themeName, tokens) => {
  it('pairs every hue with exactly one -text token', () => {
    const expected = new Set([...HUES, 'accent'].map((h) => `${h}-text`));
    for (const t of expected) expect(() => resolve(tokens, t)).not.toThrow();
    const textTokens = Object.keys(tokens).filter((k) => k.endsWith('-text'));
    expect(textTokens.sort()).toEqual([...expected].sort());
  });

  it('clears WCAG AA 4.5:1 wherever a hue is painted as text', () => {
    const failures: string[] = [];
    for (const hue of HUES) {
      const fg = hexToRgb(resolve(tokens, `${hue}-text`));
      for (const [name, bg] of Object.entries(surfaces(hue, tokens))) {
        const ratio = contrast(fg, bg);
        if (ratio < AA_NORMAL_TEXT) failures.push(`${hue}-text on ${name}: ${ratio.toFixed(2)}:1`);
      }
    }
    const accentFg = hexToRgb(resolve(tokens, 'accent-text'));
    const softPct = accentSoftPercent(tokens);
    for (const base of BASES) {
      const b = hexToRgb(resolve(tokens, base));
      const accent = hexToRgb(resolve(tokens, 'accent'));
      for (const [name, bg] of [[base, b], [`soft${softPct}/${base}`, over(accent, softPct, b)]] as const) {
        const ratio = contrast(accentFg, bg);
        if (ratio < AA_NORMAL_TEXT) failures.push(`accent-text on ${name}: ${ratio.toFixed(2)}:1`);
      }
    }
    expect(failures, `${themeName}: hue-as-text pairing(s) under ${AA_NORMAL_TEXT}:1`).toEqual([]);
  });

  it('keeps every -text token on the legible side of its own fill', () => {
    // Direction only: in light a text token is no lighter than its fill; in dark, no darker.
    const sign = themeName === 'light' ? 1 : -1;
    for (const hue of [...HUES, 'accent']) {
      const fill = luminance(hexToRgb(resolve(tokens, hue)));
      const text = luminance(hexToRgb(resolve(tokens, `${hue}-text`)));
      expect((fill - text) * sign, `${themeName}: --color-sf-${hue}-text moved the wrong way`).toBeGreaterThanOrEqual(0);
    }
  });

  it('keeps labels legible on solid fills', () => {
    const on = hexToRgb(resolve(tokens, 'on-status'));
    for (const hue of ['green', 'red'] as const) {
      expect(contrast(on, hexToRgb(resolve(tokens, hue))), `${themeName}: on-status on ${hue}`)
        .toBeGreaterThanOrEqual(AA_NORMAL_TEXT);
    }
    const inkOnAccent = contrast(hexToRgb(resolve(tokens, 'accent-ink')), hexToRgb(resolve(tokens, 'accent')));
    expect(inkOnAccent, `${themeName}: accent-ink on accent`).toBeGreaterThanOrEqual(AA_NORMAL_TEXT);
  });
});

describe('the guard itself', () => {
  it('flags a palette where each hue is its own text colour', () => {
    for (const hue of ['amber', 'green', 'ai']) {
      const regressed = { ...LIGHT_TOKENS, [`${hue}-text`]: LIGHT_TOKENS[hue] };
      expect(worstFor(hue, regressed), `reverting ${hue}-text to its fill should fail AA`).toBeLessThan(AA_NORMAL_TEXT);
    }
  });

  it('passes the palette that ships', () => {
    for (const hue of HUES) expect(worstFor(hue, LIGHT_TOKENS)).toBeGreaterThanOrEqual(AA_NORMAL_TEXT);
  });

  it('refuses a var() chain it cannot resolve', () => {
    expect(() => resolve({ 'a-text': 'var(--color-sf-nope)' }, 'a-text')).toThrow(/not declared/);
    expect(() => resolve({ 'a-text': 'color-mix(in srgb, red 5%, transparent)' }, 'a-text')).toThrow(/neither a hex/);
    expect(() => resolve({ a: 'var(--color-sf-b)', b: 'var(--color-sf-a)' }, 'a')).toThrow(/cycle/);
  });

  it('reads the real stylesheet, not an empty string', () => {
    expect(CSS.length, 'index.css did not reach the test; check vitest.config.ts `define`').toBeGreaterThan(1000);
  });
});

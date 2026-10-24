import { describe, expect, it } from 'vitest';
import {
  AA_NORMAL_TEXT, BASES, DARK_TOKENS, LIGHT_TOKENS, contrast, hexToRgb, luminance, over, type Rgb,
} from './palette.testutil';

/**
 * WCAG AA guard for the neutral ink ramp. `--color-sf-ink{,-mute,-soft,-dim}` are all body-text
 * colours, so each must clear 4.5:1 on every surface it can land on, in both themes.
 *
 * Surfaces: the three opaque bases; a 5% or 6% ink chip (`tint(INK, 5|6)`, e.g. the launcher's
 * "hidden" tag) over each; and that chip inside a hovered row (`--color-sf-hover`, whose alpha is
 * READ from the stylesheet because it differs per theme) over `bg` and `card`.
 */

const INK_TOKENS = ['ink', 'ink-mute', 'ink-soft', 'ink-dim'] as const;
const CHIP_PCTS = [5, 6] as const;

/** `--color-sf-hover`'s alpha as a percentage; asserts the hover is still an ink tint. */
function hoverPercent(t: Record<string, string>): number {
  const m = /^rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([\d.]+)\s*\)$/.exec(t.hover ?? '');
  if (!m) throw new Error(`index.css: could not read --color-sf-hover (got ${t.hover})`);
  const ink = hexToRgb(t.ink);
  if ([m[1], m[2], m[3]].map(Number).some((c, i) => c !== ink[i])) {
    throw new Error(`index.css: --color-sf-hover is no longer an ink tint (${t.hover} vs ${t.ink})`);
  }
  return Number(m[4]) * 100;
}

function surfaces(t: Record<string, string>): Record<string, Rgb> {
  const ink = hexToRgb(t.ink);
  const out: Record<string, Rgb> = {};
  for (const base of BASES) {
    const b = hexToRgb(t[base]);
    out[base] = b;
    for (const chip of CHIP_PCTS) out[`ink${chip}/${base}`] = over(ink, chip, b);
  }
  const hoverPct = hoverPercent(t);
  for (const base of ['bg', 'card'] as const) {
    const hovered = over(ink, hoverPct, hexToRgb(t[base]));
    for (const chip of CHIP_PCTS) out[`ink${chip}/hover${hoverPct}/${base}`] = over(ink, chip, hovered);
  }
  return out;
}

describe.each([
  ['light', LIGHT_TOKENS],
  ['dark', DARK_TOKENS],
])('%s theme neutral ink ramp', (themeName, tokens) => {
  it('parsed a complete palette out of index.css', () => {
    for (const k of [...INK_TOKENS, ...BASES]) {
      expect(tokens[k], `${themeName}: --color-sf-${k} missing, or not a literal hex`)
        .toMatch(/^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/);
    }
  });

  it('clears WCAG AA 4.5:1 on every surface it is painted on', () => {
    const surf = surfaces(tokens);
    // 3 raw + 3 bases x 2 chips + 2 hovered bases x 2 chips; catches a key collision.
    expect(Object.keys(surf).length).toBe(3 + 3 * 2 + 2 * 2);
    const failures: string[] = [];
    for (const token of INK_TOKENS) {
      for (const [name, bg] of Object.entries(surf)) {
        const ratio = contrast(hexToRgb(tokens[token]), bg);
        if (ratio < AA_NORMAL_TEXT) failures.push(`${token} on ${name}: ${ratio.toFixed(2)}:1`);
      }
    }
    expect(failures, `${themeName}: pairing(s) under ${AA_NORMAL_TEXT}:1`).toEqual([]);
  });

  it('keeps the four ramp steps ordered and visually distinct', () => {
    // Monotone in CIE L*, and no two steps closer than 4 L*: compressed, but still four steps.
    const lstar = (hex: string) => {
      const y = luminance(hexToRgb(hex));
      return y > 216 / 24389 ? 116 * Math.cbrt(y) - 16 : (y * 24389) / 27;
    };
    const steps = INK_TOKENS.map((t) => lstar(tokens[t]));
    const sign = themeName === 'light' ? 1 : -1;
    for (const [i, g] of steps.slice(1).map((v, j) => v - steps[j]).entries()) {
      expect(g * sign, `${INK_TOKENS[i]}->${INK_TOKENS[i + 1]} runs the wrong way`).toBeGreaterThan(0);
      expect(Math.abs(g), `${INK_TOKENS[i]}->${INK_TOKENS[i + 1]} too close`).toBeGreaterThan(4);
    }
  });
});

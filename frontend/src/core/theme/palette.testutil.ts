/**
 * Shared by the contrast guards: WCAG 2.x arithmetic and a parser for the SHIPPED `src/index.css`
 * with a fork's `public/branding/theme.css` over it (injected as `__INDEX_CSS__` and
 * `__THEME_CSS__` by `vitest.config.ts`). The guards read the real stylesheets because a copied
 * palette table would drift silently, which is the exact failure they exist to stop.
 */
declare const __INDEX_CSS__: string;
declare const __THEME_CSS__: string;
export const CSS: string = typeof __INDEX_CSS__ === 'string' ? __INDEX_CSS__ : '';
export const THEME_CSS: string = typeof __THEME_CSS__ === 'string' ? __THEME_CSS__ : '';

export const AA_NORMAL_TEXT = 4.5;
export const BASES = ['card', 'bg', 'raised'] as const;

export type Rgb = [number, number, number];

export function hexToRgb(hex: string): Rgb {
  const h = hex.replace('#', '');
  const v =
    h.length === 3
      ? h
          .split('')
          .map((c) => c + c)
          .join('')
      : h;
  if (!/^[0-9a-fA-F]{6}$/.test(v)) throw new Error(`not a hex colour: ${hex}`);
  return [0, 2, 4].map((i) => parseInt(v.slice(i, i + 2), 16)) as Rgb;
}

export function luminance([r, g, b]: Rgb): number {
  const [lr, lg, lb] = [r, g, b].map((c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * lr + 0.7152 * lg + 0.0722 * lb;
}

export function contrast(fg: Rgb, bg: Rgb): number {
  const [hi, lo] = [luminance(fg), luminance(bg)].sort((a, b) => b - a);
  return (hi + 0.05) / (lo + 0.05);
}

/**
 * `color-mix(in srgb, C pct%, transparent)` (what `shared/styles.tint()` makes) painted over an
 * opaque backdrop: a plain lerp. Channels stay float, as a browser composites a stack in one pass.
 */
export function over(color: Rgb, pct: number, under: Rgb): Rgb {
  const a = pct / 100;
  return [0, 1, 2].map((i) => color[i] * a + under[i] * (1 - a)) as Rgb;
}

/** Comments stripped first: index.css quotes hex values in prose, and dead CSS paints nothing. */
const live = (css: string) => css.replace(/\/\*[\s\S]*?\*\//g, '');

/** Every `--color-sf-*` declaration with its RAW value, so a non-hex value fails loudly later. */
function declarations(slice: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const m of slice.matchAll(/--color-sf-([a-z0-9-]+):\s*([^;]+);/g)) out[m[1]] = m[2].trim();
  return out;
}

function indexTokens(css: string) {
  const text = live(css);
  const start = text.indexOf('\n.dark {');
  if (start < 0) throw new Error('index.css: no `.dark {` block found');
  const end = text.indexOf('\n}', start);
  if (end < 0) throw new Error('index.css: unterminated `.dark {` block');
  return { light: declarations(text.slice(0, start)), dark: declarations(text.slice(start, end)) };
}

/**
 * A fork's theme.css: `:root` applies in both themes and `:root.dark` in dark only (it loads after
 * index.css, so its `:root` also beats index.css's `.dark`). Any other selector fails, because the
 * file is for tokens, not for styling app markup.
 */
export function themeTokens(css: string) {
  const root: Record<string, string> = {};
  const dark: Record<string, string> = {};
  const text = live(css);
  for (const m of text.matchAll(/([^{}]*)\{([^}]*)\}/g)) {
    const selector = m[1].trim();
    if (selector === ':root') Object.assign(root, declarations(m[2]));
    else if (selector === ':root.dark') Object.assign(dark, declarations(m[2]));
    else throw new Error(`theme.css: only :root and :root.dark blocks are allowed (got \`${selector}\`)`);
  }
  if (text.replace(/[^{}]*\{[^}]*\}/g, '').trim()) throw new Error('theme.css: text outside a :root block');
  return { root, dark };
}

/** The tokens each theme ends up with, as the browser cascades the two files. */
export function palette(indexCss: string, themeCss: string) {
  const base = indexTokens(indexCss);
  const fork = themeTokens(themeCss);
  return {
    light: { ...base.light, ...fork.root },
    dark: { ...base.light, ...base.dark, ...fork.root, ...fork.dark },
  };
}

const PALETTE = palette(CSS, THEME_CSS);
export const LIGHT_TOKENS = PALETTE.light;
export const DARK_TOKENS = PALETTE.dark;

/**
 * A token as a literal hex, following `var(--color-sf-X)` chains. Fails closed on an unknown
 * target, a non-hex non-var value and a cycle, rather than guessing a passing colour.
 */
export function resolve(tokens: Record<string, string>, name: string, seen: string[] = []): string {
  if (seen.includes(name))
    throw new Error(`index.css: --color-sf-${name} is a var() cycle (${[...seen, name].join(' -> ')})`);
  const raw = tokens[name];
  if (raw === undefined) throw new Error(`index.css: --color-sf-${name} is not declared`);
  const ref = /^var\(\s*--color-sf-([a-z0-9-]+)\s*\)$/.exec(raw);
  if (ref) return resolve(tokens, ref[1], [...seen, name]);
  if (!/^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/.test(raw)) {
    throw new Error(`index.css: --color-sf-${name} is neither a hex nor a var() chain to one (got ${raw})`);
  }
  return raw;
}

import type { CSSProperties } from 'react';

// Inline-style tokens for the shared components. Every value resolves through a
// `--color-sf-*` custom property in index.css, with NO literal fallbacks: a fallback hex here
// would pin a light-theme colour into a dark surface. New components may use the Tailwind
// `sf-*` utilities instead; both read the same properties.

export const INK = 'var(--color-sf-ink)';
export const INK_MUTE = 'var(--color-sf-ink-mute)';
export const INK_SOFT = 'var(--color-sf-ink-soft)';
export const INK_DIM = 'var(--color-sf-ink-dim)';
export const LINE = 'var(--color-sf-line)';
export const LINE_STRONG = 'var(--color-sf-line-strong)';
export const BG_CARD = 'var(--color-sf-card)';
export const BG_RAISED = 'var(--color-sf-raised)';
export const BG_PAGE = 'var(--color-sf-bg)';
export const ACCENT = 'var(--color-sf-accent)';
export const ACCENT_INK = 'var(--color-sf-accent-ink)';
export const ACCENT_TEXT = 'var(--color-sf-accent-text)';

// One hue, two tokens: `_FILL` paints a background, border or dot; `_TEXT` paints a glyph.
// The suffix is mandatory so every consumer states which role it means (see index.css).
export const GOLD_FILL = 'var(--color-sf-amber)';
export const GOLD_TEXT = 'var(--color-sf-amber-text)';
export const CORAL_FILL = 'var(--color-sf-red)';
export const CORAL_TEXT = 'var(--color-sf-red-text)';
export const SAGE_FILL = 'var(--color-sf-green)';
export const SAGE_TEXT = 'var(--color-sf-green-text)';

/** Text on a SOLID status fill (the danger confirm). Flips per theme, unlike ACCENT_INK. */
export const ON_STATUS = 'var(--color-sf-on-status)';

export const SCRIM = 'var(--color-sf-scrim)';
export const SHADOW = 'var(--color-sf-shadow)';

/** A translucent tint of a themed colour that follows the `.dark` override. */
export const tint = (color: string, pct: number): string =>
  `color-mix(in srgb, ${color} ${pct}%, transparent)`;

export const FONT_DISPLAY = 'var(--font-display)';
export const FONT_SANS = 'var(--font-sans)';
export const FONT_MONO = "ui-monospace, 'SF Mono', Menlo, monospace";

export const mono = (size: number, color: string = INK_DIM): CSSProperties => ({
  fontFamily: FONT_MONO,
  fontSize: size,
  letterSpacing: '0.16em',
  textTransform: 'uppercase',
  color,
});

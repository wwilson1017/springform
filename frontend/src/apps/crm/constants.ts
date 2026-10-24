import type { Stage } from './api';

export const STAGE_ORDER: Stage[] = ['lead', 'qualified', 'proposal', 'negotiation', 'won', 'lost'];

/** Open (non-terminal) stages: the single source of truth for "open deal". */
export const OPEN_STAGES: Stage[] = STAGE_ORDER.filter(s => s !== 'won' && s !== 'lost');

/** Derived, so a stage added to STAGE_ORDER can never leave the two lists disagreeing. */
export const CLOSED_STAGES: Stage[] = STAGE_ORDER.filter(s => !OPEN_STAGES.includes(s));

/** Mirrors the backend's MAX_REASON (lost and archive reasons). */
export const MAX_REASON = 500;

export const stageLabel = (stage: string) => stage.charAt(0).toUpperCase() + stage.slice(1);

const tint = (color: string, pct: number) => `color-mix(in srgb, ${color} ${pct}%, transparent)`;

/**
 * Stage hues live in theme.css as `--color-crm-stage-*` so the `.dark` block can lighten them.
 * Three roles, named so every consumer says which it means: `fill` paints a dot, a card's left
 * border or a bar; `text` paints the stage label; `bg` is the 12% wash, always mixed from the
 * FILL (a wash that darkened with its own label would give back the label's contrast).
 */
const stage = (name: string) => {
  const fill = `var(--color-crm-stage-${name})`;
  return { text: `var(--color-crm-stage-${name}-text)`, fill, bg: tint(fill, 12) };
};

export const STAGE_COLORS: Record<string, { text: string; fill: string; bg: string }> =
  Object.fromEntries(STAGE_ORDER.map(s => [s, stage(s)]));

/**
 * AI-estimated touch count bands: 0-4 dead zone (amber), 5-12 closing window (green), 13+
 * long cycle (the informational AI blue). One ramp, so every surface colours a count alike.
 */
export const TOUCH_COLORS = {
  low: { bg: tint('var(--color-sf-amber)', 12), text: 'var(--color-sf-amber-text)' },
  mid: { bg: tint('var(--color-sf-green)', 12), text: 'var(--color-sf-green-text)' },
  high: { bg: tint('var(--color-sf-ai)', 12), text: 'var(--color-sf-ai-text)' },
} as const;

export function touchBand(count: number): keyof typeof TOUCH_COLORS {
  return count <= 4 ? 'low' : count <= 12 ? 'mid' : 'high';
}

/** Lead-score bands: hot >= 70, warm 40-69, cool < 40. */
export type ScoreBand = 'hot' | 'warm' | 'cool';

export function scoreBand(score: number): ScoreBand {
  return score >= 70 ? 'hot' : score >= 40 ? 'warm' : 'cool';
}

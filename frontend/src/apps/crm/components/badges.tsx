import { STAGE_COLORS, TOUCH_COLORS, scoreBand, stageLabel, touchBand } from '../constants';

const pill = 'inline-flex items-center rounded px-2 py-0.5 font-mono text-xs';

/** AI-estimated touches. A null count renders nothing, so a keyless install shows no pill. */
export function TouchCountPill({ count }: { count?: number | null }) {
  if (count == null) return null;
  const c = TOUCH_COLORS[touchBand(count)];
  return (
    <span className={pill} style={{ background: c.bg, color: c.text }}
      title="AI-estimated touches, from recent notes and activity. Most deals close between touch 5 and 12.">
      {count === 1 ? '1 touch' : `${count} touches`}
    </span>
  );
}

const SCORE_COLORS = {
  cool: { bg: 'color-mix(in srgb, var(--color-sf-ink) 6%, transparent)', text: 'var(--color-sf-ink-soft)' },
  warm: { bg: 'color-mix(in srgb, var(--color-sf-amber) 12%, transparent)', text: 'var(--color-sf-amber-text)' },
  hot: { bg: 'color-mix(in srgb, var(--color-sf-green) 12%, transparent)', text: 'var(--color-sf-green-text)' },
} as const;

/** The computed 0-100 lead score (not AI; always on). A never-scored deal shows nothing. */
export function ScorePill({ score, compact }: { score?: number | null; compact?: boolean }) {
  if (score == null) return null;
  const c = SCORE_COLORS[scoreBand(score)];
  return (
    <span className={pill} style={{ background: c.bg, color: c.text }}
      title="Lead score (0-100) from stage, engagement, value, links and recency.">
      {compact ? score : `Score ${score}`}
    </span>
  );
}

export function StageBadge({ stage }: { stage: string }) {
  const c = STAGE_COLORS[stage];
  return (
    <span className="inline-flex items-center gap-1.5 rounded px-2 py-0.5 text-xs font-medium"
      style={{ background: c?.bg, color: c?.text }}>
      <span aria-hidden className="h-2 w-2 rounded-full" style={{ background: c?.fill }} />
      {stageLabel(stage)}
    </span>
  );
}

export function StageDot({ stage }: { stage: string }) {
  return <span aria-hidden className="inline-block h-2 w-2 shrink-0 rounded-full" style={{ background: STAGE_COLORS[stage]?.fill }} />;
}

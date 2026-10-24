import type { ReactNode } from 'react';

/** The frame every page here shares: a title, an optional line under it, actions on the right. */
export function Page({ title, intro, actions, children }: { title: string; intro?: ReactNode; actions?: ReactNode; children: ReactNode }) {
  return (
    <div className="mx-auto max-w-5xl px-4 py-8 md:px-8">
      <div className="mb-6 flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1 basis-60">
          <h1 className="m-0 font-display text-2xl font-medium text-sf-ink">{title}</h1>
          {intro && <p className="mt-1 mb-0 text-sm text-sf-ink-soft">{intro}</p>}
        </div>
        {actions}
      </div>
      {children}
    </div>
  );
}

export function Chip({ children, tone = 'plain' }: { children: ReactNode; tone?: 'plain' | 'green' | 'red' | 'amber' }) {
  const tones = {
    plain: 'bg-sf-ink/6 text-sf-ink-mute',
    green: 'bg-sf-green/15 text-sf-green-text',
    red: 'bg-sf-red/12 text-sf-red-text',
    amber: 'bg-sf-amber/15 text-sf-amber-text',
  };
  return <span className={`inline-block rounded px-1.5 py-0.5 text-xs whitespace-nowrap ${tones[tone]}`}>{children}</span>;
}

export const inputClass =
  'rounded-md border border-sf-line-strong bg-sf-card px-3 py-2 font-sans text-sm text-sf-ink placeholder:text-sf-ink-dim';
export const buttonClass =
  'cursor-pointer rounded-md border-0 bg-sf-accent px-4 py-2 font-sans text-sm font-medium text-sf-accent-ink disabled:cursor-default disabled:opacity-50';
export const quietButtonClass =
  'cursor-pointer rounded-md border border-sf-line-strong bg-transparent px-3 py-1.5 font-sans text-sm text-sf-ink-mute hover:bg-sf-hover disabled:cursor-default disabled:opacity-50';

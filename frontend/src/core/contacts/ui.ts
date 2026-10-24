// Tailwind class strings shared by the contacts screens (the `sf-*` tokens follow the theme).

export const btn = 'inline-flex cursor-pointer items-center gap-1.5 rounded-md px-3 py-1.5 font-sans text-sm disabled:cursor-default disabled:opacity-50';
export const btnPrimary = `${btn} border-0 bg-sf-accent font-medium text-sf-accent-ink`;
export const btnSecondary = `${btn} border border-sf-line-strong bg-transparent text-sf-ink-mute hover:bg-sf-hover`;
export const btnDanger = `${btn} border border-sf-line-strong bg-transparent text-sf-red-text hover:bg-sf-hover`;
/** A text-only action inside a row ("Edit", "Remove"). */
export const btnLink = 'cursor-pointer border-0 bg-transparent p-0 font-sans text-xs text-sf-accent-text disabled:opacity-50';
export const input = 'w-full rounded-md border border-sf-line-strong bg-sf-card px-3 py-2 text-sm text-sf-ink placeholder:text-sf-ink-dim';
export const label = 'mb-1 block text-xs font-medium text-sf-ink-mute';
export const chip = 'inline-block rounded bg-sf-raised px-1.5 py-0.5 text-xs text-sf-ink-mute';
export const sectionTitle = 'm-0 mb-3 font-display text-base font-medium text-sf-ink';
export const card = 'rounded-lg border border-sf-line-strong bg-sf-card';

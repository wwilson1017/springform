import type { ReactNode } from 'react';

/** The centred card the signed-out pages share. */
export function AuthLayout({ subtitle, children }: { subtitle: string; children: ReactNode }) {
  return (
    <div className="flex min-h-svh items-center justify-center bg-sf-bg px-7">
      <div className="w-full max-w-sm">
        <div className="mb-10 text-center">
          <h1 className="m-0 font-display text-3xl font-medium text-sf-ink">Springform</h1>
          <p className="mt-2 text-sm text-sf-ink-mute">{subtitle}</p>
        </div>
        {children}
      </div>
    </div>
  );
}

export const labelClass = 'block text-xs font-medium uppercase tracking-wider text-sf-ink-soft mb-1.5';
export const inputClass =
  'w-full box-border border border-sf-line-strong rounded-md px-3.5 py-3 bg-sf-card text-base text-sf-ink placeholder:text-sf-ink-dim';
export const buttonClass =
  'w-full bg-sf-accent text-sf-accent-ink border-none text-sm font-medium px-4 py-3 rounded-md cursor-pointer disabled:opacity-50';

import type { CoreApp } from '../api/types';

/** The install's own name for core topics and records. */
export const CORE_LABEL = 'Springform';

/** An app slug as a person reads it: the installed app's name, "Springform" for core. */
export function appName(apps: CoreApp[] | null, slug: string | null | undefined): string {
  if (!slug || slug === 'core') return CORE_LABEL;
  return apps?.find(a => a.slug === slug)?.name ?? slug;
}

/** A change-log value: JSON of any shape, shown on one line. */
export function formatValue(v: unknown): string {
  if (v === null || v === undefined || v === '') return 'empty';
  return typeof v === 'string' ? v : JSON.stringify(v);
}

/** Seconds as "<1 s", "45 s", "15 min", "2 h". */
export function formatSeconds(s: number): string {
  if (s < 1) return '<1 s';
  if (s < 60) return `${Math.round(s)} s`;
  if (s < 3600) return `${Math.round(s / 60)} min`;
  return `${+(s / 3600).toFixed(1)} h`;
}

/** Guide snippets are raw Markdown lines; drop emphasis marks and a leading list marker so they read as prose. */
export const plainSnippet = (s: string) => s.replace(/\*\*|__|`/g, '').replace(/^\s*(?:[-*]|\d+\.)\s+/, '');

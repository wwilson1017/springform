import type { ReminderFreq } from './types';

export const REMINDERS = '/api/core/reminders';

export const REPEAT_LABEL: Record<ReminderFreq, string> = { daily: 'Every day', weekly: 'Every week', monthly: 'Every month', yearly: 'Every year' };

const pad = (n: number) => String(n).padStart(2, '0');

/** An instant as a `datetime-local` value in the browser's zone. */
export function toLocalInput(iso: string | Date): string {
  const d = new Date(iso);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** A `datetime-local` (or `date`) value, read in the browser's zone, as a UTC instant. */
export function fromLocalInput(local: string): string {
  return new Date(local.length === 10 ? `${local}T00:00` : local).toISOString();
}

/** The next whole hour after now, a sensible default due time. */
export function nextHour(now = new Date()): Date {
  const d = new Date(now);
  d.setMinutes(0, 0, 0);
  d.setHours(d.getHours() + 1);
  return d;
}

/** Snooze choices relative to `now`, in the browser's zone. */
export function snoozePresets(now = new Date()): Array<{ label: string; until: string }> {
  const at = (days: number, hour: number) => {
    const d = new Date(now);
    d.setDate(d.getDate() + days);
    d.setHours(hour, 0, 0, 0);
    return d;
  };
  const daysToMonday = ((8 - now.getDay()) % 7) || 7;
  return [
    { label: 'In 1 hour', until: new Date(now.getTime() + 3_600_000) },
    { label: 'In 3 hours', until: new Date(now.getTime() + 3 * 3_600_000) },
    { label: 'Tomorrow at 9 AM', until: at(1, 9) },
    { label: 'Next Monday at 9 AM', until: at(daysToMonday, 9) },
  ].map(p => ({ label: p.label, until: p.until.toISOString() }));
}

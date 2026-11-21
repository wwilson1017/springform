/** Check-in schedule text (`every:60`, `daily@09:00`, `weekly:mon@09:00`) to and from the form and the list. */

export type Kind = 'every' | 'daily' | 'weekly';
export const DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'] as const;
export const DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

/** The stored schedule text: `every:60`, `daily@09:00`, `weekly:mon@09:00`. */
export function scheduleText(kind: Kind, minutes: number, day: string, time: string): string {
  if (kind === 'every') return `every:${minutes}`;
  return kind === 'daily' ? `daily@${time}` : `weekly:${day}@${time}`;
}

/** The schedule in words, for the list. */
export function describeSchedule(text: string): string {
  const every = /^every:(\d+)$/.exec(text);
  if (every) return `Every ${every[1]} minutes`;
  const daily = /^daily@(\d\d:\d\d)$/.exec(text);
  if (daily) return `Daily at ${daily[1]}`;
  const weekly = /^weekly:(\w{3})@(\d\d:\d\d)$/.exec(text);
  const i = weekly ? DAYS.indexOf(weekly[1] as (typeof DAYS)[number]) : -1;
  return weekly && i >= 0 ? `${DAY_NAMES[i]}s at ${weekly[2]}` : text;
}

/**
 * Format an ISO instant as a short "Mon D, h:mm AM" label in the browser's zone. The backend
 * writes `YYYY-MM-DDTHH:MM:SSZ`; a bare naive string is read as UTC rather than local.
 */
export function formatDate(iso: string): string {
  try {
    const hasZone = /[Zz]|[+-]\d\d:?\d\d$/.test(iso);
    const d = new Date(hasZone ? iso : iso + 'Z');
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) +
      ' ' + d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
  } catch { return iso; }
}

/**
 * Money is integer cents on the wire. These are the only places the UI turns cents into text
 * or typed text back into cents, so no float ever reaches the API.
 */

/** "$4,800" for whole amounts, "$6,750.50" otherwise. */
export function formatCents(cents: number | null | undefined, currency = 'USD'): string {
  if (cents == null) return '—';
  const whole = cents % 100 === 0;
  try {
    return new Intl.NumberFormat(undefined, {
      style: 'currency', currency,
      minimumFractionDigits: whole ? 0 : 2, maximumFractionDigits: whole ? 0 : 2,
    }).format(cents / 100);
  } catch {
    // An unknown currency code: Intl throws, so fall back to the bare number and the code.
    return `${(cents / 100).toLocaleString(undefined, { minimumFractionDigits: whole ? 0 : 2 })} ${currency}`;
  }
}

/** The editable text for a cents value: "4800" or "6750.50"; '' for 0. */
export function centsToInput(cents: number): string {
  if (!cents) return '';
  return cents % 100 === 0 ? String(cents / 100) : (cents / 100).toFixed(2);
}

/**
 * Typed text to cents, or null when it is not an amount. Accepts "4,800", "$4800.5", "-20";
 * more than two decimals is refused rather than rounded, so nothing is silently changed.
 * The arithmetic is on the digit string, never `parseFloat(x) * 100`, which drifts (1.15).
 */
export function inputToCents(text: string): number | null {
  const cleaned = text.trim().replace(/[$,\s]/g, '');
  if (cleaned === '') return 0;
  const m = /^(-)?(\d*)(?:\.(\d{0,2}))?$/.exec(cleaned);
  if (!m || (m[2] === '' && !m[3])) return null;
  const cents = Number(m[2] || '0') * 100 + Number((m[3] ?? '').padEnd(2, '0'));
  return m[1] ? -cents : cents;
}

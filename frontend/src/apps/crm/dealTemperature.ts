/**
 * The rep's own read on a deal, as pure rules. `deal_temperature` holds `'hot' | 'warm' |
 * 'cold'`, or null when nobody has triaged the deal. **Null is not `'cold'`**: cold is a judgment
 * someone made (it moves the lead score), untriaged is no judgment at all.
 */

/** The stored tiers, coldest to hottest, spelled as the server stores them. */
export const DEAL_TEMPERATURES = ['cold', 'warm', 'hot'] as const;

export type DealTemperature = (typeof DEAL_TEMPERATURES)[number];

/** Narrow a wire value to a tier; anything unrecognised reads as untriaged. */
export function normalizeTemperature(value: string | null | undefined): DealTemperature | null {
  if (typeof value !== 'string') return null;
  const cleaned = value.trim().toLowerCase();
  return (DEAL_TEMPERATURES as readonly string[]).includes(cleaned) ? (cleaned as DealTemperature) : null;
}

/**
 * The click cycle: `not set → hot → warm → cold → not set`. An untriaged deal goes to hot first
 * (flagging the deal you care about is one click), and the cycle returns to unset so a mis-click
 * is never permanent.
 */
export function nextTemperature(value: string | null | undefined): DealTemperature | null {
  switch (normalizeTemperature(value)) {
    case null: return 'hot';
    case 'hot': return 'warm';
    case 'warm': return 'cold';
    case 'cold': return null;
  }
}

/** Display word for a tier or for the untriaged state (the control's title and aria-label). */
export function temperatureLabel(value: string | null | undefined): string {
  const tier = normalizeTemperature(value);
  return tier === null ? 'not set' : tier.charAt(0).toUpperCase() + tier.slice(1);
}

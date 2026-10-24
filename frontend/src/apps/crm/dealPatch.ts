/** The deal page's edit form as pure rules: the form state from a deal, and the patch of only
 *  the fields that changed (so a save never rewrites what someone else just edited). */
import type { Deal, DealPatch } from './api';
import { centsToInput, inputToCents } from './money';

export interface Form {
  title: string; value: string; currency: string; probability: string; expected_close: string; closed_on: string;
  person: { id: number; name: string } | null; organization: { id: number; name: string } | null;
  owner: number | null; temperature: string; notes: string;
}

export const toForm = (d: Deal): Form => ({
  title: d.title, value: centsToInput(d.value_cents), currency: d.currency, probability: String(d.probability),
  expected_close: d.expected_close ?? '', closed_on: d.closed_on ?? '',
  person: d.person_id ? { id: d.person_id, name: d.person_name ?? `Person ${d.person_id}` } : null,
  organization: d.organization_id ? { id: d.organization_id, name: d.organization_name ?? `Organization ${d.organization_id}` } : null,
  owner: d.owner_user_id, temperature: d.deal_temperature ?? '', notes: d.notes,
});

/** The changed fields as a DealPatch, or the first validation message. */
export function buildPatch(f: Form, base: Form): DealPatch | string {
  const patch: DealPatch = {};
  if (!f.title.trim()) return 'A title is required.';
  if (f.title.trim() !== base.title) patch.title = f.title.trim();
  const cents = inputToCents(f.value);
  if (cents === null) return 'Value must be an amount, like 4800 or 4,800.50.';
  if (cents !== inputToCents(base.value)) patch.value_cents = cents;
  if (!/^[A-Za-z]{3}$/.test(f.currency.trim())) return 'Currency is a three-letter code, like USD.';
  if (f.currency.trim().toUpperCase() !== base.currency) patch.currency = f.currency.trim().toUpperCase();
  const prob = Number(f.probability);
  if (f.probability === '' || !Number.isInteger(prob) || prob < 0 || prob > 100) return 'Probability is a whole number from 0 to 100.';
  if (prob !== Number(base.probability)) patch.probability = prob;
  if (f.expected_close !== base.expected_close) patch.expected_close = f.expected_close || null;
  if (f.closed_on !== base.closed_on && f.closed_on) patch.closed_on = f.closed_on;
  if ((f.person?.id ?? null) !== (base.person?.id ?? null)) patch.person_id = f.person?.id ?? null;
  if ((f.organization?.id ?? null) !== (base.organization?.id ?? null)) patch.organization_id = f.organization?.id ?? null;
  if (f.owner !== base.owner) patch.owner_user_id = f.owner;
  if (f.temperature !== base.temperature) patch.deal_temperature = (f.temperature || null) as DealPatch['deal_temperature'];
  if (f.notes !== base.notes) patch.notes = f.notes;
  return patch;
}

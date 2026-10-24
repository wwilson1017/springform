import type { Deal, DealDetail } from './api';

let nextId = 100;

/** A deal as the API returns it; override what the test is about. */
export function deal(over: Partial<Deal> = {}): Deal {
  const id = over.id ?? nextId++;
  return {
    id, title: `Deal ${id}`, stage: 'lead', status: 'open', value_cents: 100_000, currency: 'USD', probability: 0,
    expected_close: null, closed_on: null, lost_reason: '', deal_temperature: null, notes: '',
    person_id: null, person_name: null, organization_id: null, organization_name: null,
    owner_user_id: 1, owner_name: 'Ada Admin', lead_score: null, lead_score_at: null,
    ai_touch_count: null, ai_touch_count_at: null, last_activity_at: null,
    archived_at: null, archived_by: null, archived_reason: null,
    created_at: '2026-10-01T15:00:00Z', updated_at: '2026-10-20T15:00:00Z',
    ...over,
  };
}

export function detail(over: Partial<DealDetail> = {}): DealDetail {
  return { ...deal(over), activity: [], stage_events: [], ...over };
}

import { describe, expect, it } from 'vitest';
import { deal } from './crm.testutil';
import { NO_FILTERS, filterDeals, groupByStage, movedDeal, openTotals, visibleStages } from './pipelineBoard';

describe('groupByStage', () => {
  it('puts each deal in its stage column, in pipeline order, with that column’s count and total', () => {
    const deals = [
      deal({ id: 1, stage: 'proposal', value_cents: 480_000 }),
      deal({ id: 2, stage: 'lead', value_cents: 900_000 }),
      deal({ id: 3, stage: 'proposal', value_cents: 20_050 }),
      deal({ id: 4, stage: 'won', value_cents: 675_050 }),
    ];
    const cols = groupByStage(deals);
    expect(cols.map(c => c.stage)).toEqual(['lead', 'qualified', 'proposal', 'negotiation', 'won', 'lost']);
    const proposal = cols.find(c => c.stage === 'proposal')!;
    expect(proposal.deals.map(d => d.id)).toEqual([1, 3]);
    expect([proposal.count, proposal.totalCents]).toEqual([2, 500_050]);
    expect(cols.find(c => c.stage === 'qualified')).toMatchObject({ count: 0, totalCents: 0, deals: [] });
  });

  it('shows only the stages asked for (won and lost hidden by default)', () => {
    const cols = groupByStage([deal({ stage: 'won' }), deal({ stage: 'lead' })], visibleStages(false));
    expect(cols.map(c => c.stage)).toEqual(['lead', 'qualified', 'proposal', 'negotiation']);
  });

  it('orders a column by lead score, highest first, unscored last, ties in server order', () => {
    const cols = groupByStage([
      deal({ id: 1, lead_score: null }), deal({ id: 2, lead_score: 40 }), deal({ id: 3, lead_score: 80 }), deal({ id: 4, lead_score: 40 }),
    ]);
    expect(cols[0].deals.map(d => d.id)).toEqual([3, 2, 4, 1]);
  });
});

describe('filterDeals', () => {
  const deals = [
    deal({ id: 1, owner_user_id: 1, deal_temperature: 'hot' }),
    deal({ id: 2, owner_user_id: 2, deal_temperature: null }),
    deal({ id: 3, owner_user_id: null, deal_temperature: 'cold' }),
  ];
  const ids = (f: Partial<typeof NO_FILTERS>) => filterDeals(deals, { ...NO_FILTERS, ...f }).map(d => d.id);

  it('filters by owner, including unassigned', () => {
    expect(ids({ owner: '2' })).toEqual([2]);
    expect(ids({ owner: 'unassigned' })).toEqual([3]);
    expect(ids({})).toEqual([1, 2, 3]);
  });

  it('keeps untriaged apart from cold', () => {
    expect(ids({ temperature: 'none' })).toEqual([2]);
    expect(ids({ temperature: 'cold' })).toEqual([3]);
  });

  it('narrows to a search’s matches only once a search has answered', () => {
    expect(ids({ matchIds: new Set([3, 99]) })).toEqual([3]);
    expect(ids({ matchIds: null })).toEqual([1, 2, 3]);
  });
});

describe('movedDeal and openTotals', () => {
  it('applies the server’s stage rules optimistically', () => {
    const lost = deal({ stage: 'lost', status: 'lost', lost_reason: 'Budget' });
    expect(movedDeal(lost, 'qualified', '2026-10-24')).toMatchObject({ stage: 'qualified', status: 'open', lost_reason: '' });
    expect(movedDeal(deal({ probability: 30 }), 'won', '2026-10-24')).toMatchObject({ status: 'won', probability: 100, closed_on: '2026-10-24' });
    expect(movedDeal(deal({ stage: 'won', closed_on: '2026-10-01' }), 'negotiation', '2026-10-24')).toMatchObject({ closed_on: null, status: 'open' });
  });

  it('totals open, live deals only', () => {
    const deals = [
      deal({ stage: 'lead', value_cents: 100 }), deal({ stage: 'won', value_cents: 1_000 }),
      deal({ stage: 'proposal', value_cents: 10, archived_at: '2026-10-02T00:00:00Z' }),
    ];
    expect(openTotals(deals)).toEqual({ count: 1, cents: 100 });
  });
});

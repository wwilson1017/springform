import { afterEach, describe, expect, it, vi } from 'vitest';
import { callsTo, mockFetch } from '../../testing';
import { resetStageCriteria, saveStageCriteria } from './api';

afterEach(() => vi.unstubAllGlobals());

const lead = { stage: 'lead', summary: 'A new inquiry', checklist: ['Name captured'], is_default: true, updated_at: null };

describe('stage criteria calls', () => {
  it('saves with a PUT of the summary and checklist', async () => {
    const fetchMock = mockFetch({ 'PUT /api/crm/stage-criteria/lead': { body: { ...lead, is_default: false } } });
    expect((await saveStageCriteria('lead', { summary: 'S', checklist: ['a'] })).is_default).toBe(false);
    expect(JSON.parse(callsTo(fetchMock, 'PUT', '/api/crm/stage-criteria/lead')[0][1]!.body as string)).toEqual({ summary: 'S', checklist: ['a'] });
  });

  it('resets with a DELETE, then answers the standard criteria read back', async () => {
    const fetchMock = mockFetch({
      'DELETE /api/crm/stage-criteria/lead': { body: lead },
      'GET /api/crm/stage-criteria': { body: [lead, { ...lead, stage: 'won' }] },
    });
    expect(await resetStageCriteria('lead')).toEqual(lead);
    expect(callsTo(fetchMock, 'DELETE', '/api/crm/stage-criteria/lead')).toHaveLength(1);
  });
});

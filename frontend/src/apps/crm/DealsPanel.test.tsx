import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { callsTo, mockFetch } from '../../testing';
import { deal } from './crm.testutil';
import DealsPanel from './DealsPanel';

afterEach(() => vi.unstubAllGlobals());

describe('DealsPanel', () => {
  it("lists a person's deals with stage and value, each linking to its deal page", async () => {
    mockFetch({
      'GET /api/crm/people/5/deals': { body: [deal({ id: 1, title: 'Spring order', stage: 'proposal', value_cents: 480_000 })] },
      'GET /api/core/contacts/people/5': { body: { id: 5, name: 'Ada' } },
    });
    render(<MemoryRouter><DealsPanel entityType="core.person" entityId={5} /></MemoryRouter>);
    const link = await screen.findByRole('link', { name: /Spring order/ });
    expect(link.getAttribute('href')).toBe('/crm/deals/1');
    expect(link.textContent).toContain('Proposal');
    expect(link.textContent).toContain('$4,800');
    expect(screen.getByRole('button', { name: 'New deal' })).toBeTruthy();
  });

  it("reads an organization's deals from the organization route", async () => {
    const fetchMock = mockFetch({
      'GET /api/crm/organizations/9/deals': { body: [] },
      'GET /api/core/contacts/organizations/9': { body: { id: 9, name: 'Example Bakery Supply' } },
    });
    render(<MemoryRouter><DealsPanel entityType="core.organization" entityId={9} /></MemoryRouter>);
    expect(await screen.findByText('No deals yet.')).toBeTruthy();
    expect(callsTo(fetchMock, 'GET', '/api/crm/organizations/9/deals')).toHaveLength(1);
  });
});

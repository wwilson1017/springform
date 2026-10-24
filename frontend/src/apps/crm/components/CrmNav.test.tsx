import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { describe, expect, it } from 'vitest';
import { CrmNav } from './CrmNav';

describe('CrmNav', () => {
  it('links to the CRM screens from deep inside the /crm/* splat, not relative to the URL', () => {
    render(
      <MemoryRouter initialEntries={['/crm/deals/7']}>
        <Routes><Route path="/crm/*" element={<CrmNav />} /></Routes>
      </MemoryRouter>,
    );
    expect(screen.getByRole('link', { name: 'Pipeline' }).getAttribute('href')).toBe('/crm/deals');
    expect(screen.getByRole('link', { name: 'Dashboard' }).getAttribute('href')).toBe('/crm');
    expect(screen.getByRole('link', { name: 'Pipeline' }).getAttribute('aria-current')).toBe('page');
  });
});

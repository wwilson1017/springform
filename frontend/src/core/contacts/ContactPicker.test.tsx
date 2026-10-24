import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { mockFetch } from '../../testing';
import { ContactPicker } from './ContactPicker';

const SEARCH = '/api/core/contacts/search?q=demo&kind=organization&limit=20';

afterEach(() => vi.unstubAllGlobals());

describe('ContactPicker', () => {
  it('searches by kind and hands back the chosen record', async () => {
    mockFetch({ [`GET ${SEARCH}`]: { body: [{ kind: 'organization', id: 3, name: 'Demo Café Group', email: null, phone: null, url: '/organizations/3' }] } });
    const onChange = vi.fn();
    render(<ContactPicker kind="organization" value={null} onChange={onChange} />);
    const box = screen.getByRole('combobox');
    fireEvent.focus(box);
    fireEvent.change(box, { target: { value: 'demo' } });
    fireEvent.click(await screen.findByRole('option', { name: 'Demo Café Group' }));
    expect(onChange).toHaveBeenCalledWith({ id: 3, name: 'Demo Café Group' });
    // No create row without allowCreate.
    expect(screen.queryByText(/Create "/)).toBeNull();
  });

  it('creating a name an organization already holds links to that organization', async () => {
    mockFetch({
      [`GET ${SEARCH}`]: { body: [] },
      'POST /api/core/contacts/organizations': { status: 409, body: { detail: 'organization #3 already has that name' } },
      'GET /api/core/contacts/organizations/3': { body: { id: 3, name: 'Demo' } },
    });
    const onChange = vi.fn();
    render(<ContactPicker kind="organization" value={null} onChange={onChange} allowCreate />);
    const box = screen.getByRole('combobox');
    fireEvent.focus(box);
    fireEvent.change(box, { target: { value: 'demo' } });
    fireEvent.click(await screen.findByRole('option', { name: 'Create "demo"…' }));
    await vi.waitFor(() => expect(onChange).toHaveBeenCalledWith({ id: 3, name: 'Demo' }));
  });
});

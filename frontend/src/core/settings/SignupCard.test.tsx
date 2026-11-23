import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { callsTo, mockFetch } from '../../testing';
import SignupCard from './SignupCard';

const settings = (list: string[]) => ({
  values: { 'auth.signup_allow': list },
  secrets: {},
  defaults: { 'auth.signup_allow': [] },
});

afterEach(() => vi.unstubAllGlobals());

describe('SignupCard', () => {
  it('saves one entry per line and shows the cleaned list back', async () => {
    const fetchMock = mockFetch({
      'GET /api/core/settings': { body: settings(['@example.com']) },
      'PUT /api/core/settings': { body: settings(['@example.com', 'pat@example.org']) },
    });
    render(<SignupCard />);
    const box = (await screen.findByLabelText(/one per line/)) as HTMLTextAreaElement;
    expect(box.value).toBe('@example.com');
    fireEvent.change(box, { target: { value: '@example.com\n Pat@Example.org ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(box.value).toBe('@example.com\npat@example.org'));
    const [put] = callsTo(fetchMock, 'PUT', '/api/core/settings');
    expect(JSON.parse(String(put[1]?.body))).toEqual({
      values: { 'auth.signup_allow': ['@example.com', ' Pat@Example.org '] },
    });
  });

  it('shows the server reason for an entry it refuses', async () => {
    mockFetch({
      'GET /api/core/settings': { body: settings([]) },
      'PUT /api/core/settings': {
        status: 422,
        body: { detail: "auth.signup_allow: 'example.com' is not @domain or name@domain" },
      },
    });
    render(<SignupCard />);
    fireEvent.change(await screen.findByLabelText(/one per line/), { target: { value: 'example.com' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect((await screen.findByRole('alert')).textContent).toMatch(/is not @domain or name@domain/);
  });
});

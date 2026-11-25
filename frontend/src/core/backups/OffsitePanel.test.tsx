import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { callsTo, mockFetch } from '../../testing';
import { offsite } from './testFixtures';
import { OffsitePanel } from './OffsitePanel';

afterEach(() => vi.unstubAllGlobals());

const saved = offsite({
  configured: true,
  endpoint: 'https://s3.example.com',
  bucket: 'shop-backups',
  region: 'auto',
  access_key_id: 'AKID',
  retention: 30,
  last_success_at: '2026-11-01T03:00:05Z',
  last_success_bytes: 2048,
  last_error: 'The storage service answered HTTP 403: AccessDenied',
  stale: true,
});

describe('OffsitePanel', () => {
  it('shows the last upload, the error, the stale line and the lost-passphrase warning', () => {
    render(<OffsitePanel offsite={saved} onChanged={() => {}} />);
    expect(screen.getByText(/Last good upload:.*2 KB/)).toBeTruthy();
    expect(screen.getByText('Last error: The storage service answered HTTP 403: AccessDenied')).toBeTruthy();
    expect(screen.getByText('No good off-site upload in more than two days.')).toBeTruthy();
    expect(screen.getByText(/If you lose this passphrase, the encrypted backups cannot be opened/)).toBeTruthy();
    expect(screen.getByText(/does not hold the\s+encryption key/)).toBeTruthy();
  });

  it('saves the destination without sending a blank secret', async () => {
    const fetch = mockFetch({ 'PUT /api/core/backups/destination': { body: saved } });
    const onChanged = vi.fn();
    render(<OffsitePanel offsite={saved} onChanged={onChanged} />);
    fireEvent.change(screen.getByLabelText('Bucket'), { target: { value: 'other' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save destination' }));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    const [, init] = callsTo(fetch, 'PUT', '/api/core/backups/destination')[0];
    expect(JSON.parse(init?.body as string)).toEqual({
      endpoint: 'https://s3.example.com',
      bucket: 'other',
      region: 'auto',
      prefix: '',
      access_key_id: 'AKID',
      secret_key: null,
      retention: 30,
    });
  });

  it("shows the storage service's refusal from a failed connection test", async () => {
    mockFetch({
      'POST /api/core/backups/destination/test': {
        status: 502,
        body: { detail: 'The storage service answered HTTP 403: AccessDenied' },
      },
    });
    render(<OffsitePanel offsite={offsite({ ...saved, last_error: null })} onChanged={() => {}} />);
    fireEvent.click(screen.getByRole('button', { name: 'Test connection' }));
    expect((await screen.findByRole('alert')).textContent).toBe('The storage service answered HTTP 403: AccessDenied');
  });

  it('holds Test connection while the destination has unsaved edits', () => {
    render(<OffsitePanel offsite={saved} onChanged={() => {}} />);
    const test = screen.getByRole('button', { name: 'Test connection' }) as HTMLButtonElement;
    expect(test.disabled).toBe(false);
    fireEvent.change(screen.getByLabelText('Bucket'), { target: { value: 'other' } });
    expect(test.disabled).toBe(true);
  });
});

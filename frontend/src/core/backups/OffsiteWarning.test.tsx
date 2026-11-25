import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { mockFetch } from '../../testing';
import { offsite } from './testFixtures';
import { OffsiteWarning } from './OffsiteWarning';

afterEach(() => vi.unstubAllGlobals());

const overview = (extra: Parameters<typeof offsite>[0]) => ({
  sets: [],
  last_backup_at: null,
  last_run: null,
  key_source: 'file',
  key_shown: true,
  key_mismatch: null,
  offsite: offsite({ configured: true, ...extra }),
});

function setup(isAdmin: boolean, body: object) {
  const fetch = mockFetch({ 'GET /api/core/backups': { body } });
  render(
    <MemoryRouter>
      <OffsiteWarning isAdmin={isAdmin} />
    </MemoryRouter>,
  );
  return fetch;
}

describe('OffsiteWarning', () => {
  it('warns an admin when the off-site copy is stale, linking to Backups', async () => {
    setup(true, overview({ stale: true }));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('No good off-site backup in more than two days.');
    expect(screen.getByRole('link', { name: 'Open Backups' }).getAttribute('href')).toBe('/backups');
  });

  it('says the last upload failed', async () => {
    setup(true, overview({ last_error: 'nope' }));
    expect((await screen.findByRole('alert')).textContent).toContain('The last off-site backup failed.');
  });

  it('asks nothing for a member', () => {
    const fetch = setup(false, overview({ stale: true }));
    expect(fetch).not.toHaveBeenCalled();
    expect(screen.queryByRole('alert')).toBeNull();
  });
});

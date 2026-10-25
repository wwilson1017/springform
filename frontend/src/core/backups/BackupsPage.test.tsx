import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { mockFetch } from '../../testing';
import BackupsPage from './BackupsPage';
import type { BackupsOverview } from './types';

afterEach(() => vi.unstubAllGlobals());

const overview = (extra: Partial<BackupsOverview> = {}): BackupsOverview => ({
  sets: [], last_backup_at: null, last_run: null, key_source: 'env', key_shown: false, key_mismatch: null, ...extra,
});

function setup(body: BackupsOverview) {
  mockFetch({
    'GET /api/core/backups': { body },
    'POST /api/core/backups/key': { body: { key_source: 'env', fingerprint: 'fp-1' } },
  });
  render(<MemoryRouter><BackupsPage /></MemoryRouter>);
}

describe('BackupsPage key mismatch', () => {
  it('warns, naming the manifest and linking the Guide, when the key does not match the newest backup', async () => {
    setup(overview({ key_mismatch: '20261101T030000Z.manifest.json' }));
    const banner = await screen.findByRole('alert');
    expect(banner.textContent).toContain(
      'The encryption key on this server does not match the newest backup (20261101T030000Z.manifest.json). '
      + 'Stored credentials cannot be read until the matching key is restored.');
    expect(screen.getByRole('link', { name: 'How to restore the key' }).getAttribute('href')).toBe('/guide/backups-and-restore');
  });

  it('shows no warning when the key matches', async () => {
    setup(overview());
    expect(await screen.findByText('No backups yet.')).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
  });
});

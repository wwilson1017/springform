import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { callsTo, mockFetch } from '../../testing';
import { KeyPanel } from './KeyPanel';

const KEY_URL = '/api/core/backups/key';

afterEach(() => vi.unstubAllGlobals());

describe('KeyPanel', () => {
  it('env key: says where the key lives and shows only its fingerprint', async () => {
    mockFetch({ [`POST ${KEY_URL}`]: { body: { key_source: 'env', fingerprint: 'fp-env-1' } } });
    render(<KeyPanel keySource="env" keyShown={false} />);
    expect(screen.getByText('Your key is in your environment; keep it with your .env.')).toBeTruthy();
    expect(await screen.findByText('fp-env-1')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Show key once' })).toBeNull();
  });

  it('key file, not yet shown: one click reveals the key, its fingerprint and the off-site warning', async () => {
    const fetchMock = mockFetch({ [`POST ${KEY_URL}`]: { body: { key_source: 'file', key: 'k3y-secret=', fingerprint: 'fp-file-1' } } });
    const writeText = vi.fn(() => Promise.resolve());
    vi.stubGlobal('navigator', { clipboard: { writeText } });
    render(<KeyPanel keySource="file" keyShown={false} />);

    fireEvent.click(screen.getByRole('button', { name: 'Show key once' }));
    expect((await screen.findByTestId('encryption-key')).textContent).toBe('k3y-secret=');
    expect(screen.getByText('fp-file-1')).toBeTruthy();
    expect(screen.getByText('Store this off-site; without it a restored copy cannot read stored credentials.')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Show key once' })).toBeNull();
    expect(callsTo(fetchMock, 'POST', KEY_URL)).toHaveLength(1);

    fireEvent.click(screen.getByRole('button', { name: 'Copy' }));
    expect(writeText).toHaveBeenCalledWith('k3y-secret=');
  });

  it('key file shown elsewhere since the page loaded: the 410 becomes the already-shown state', async () => {
    mockFetch({ [`POST ${KEY_URL}`]: { status: 410, body: { detail: 'key_already_shown' } } });
    render(<KeyPanel keySource="file" keyShown={false} />);
    fireEvent.click(screen.getByRole('button', { name: 'Show key once' }));
    expect(await screen.findByText(/The key was already shown/)).toBeTruthy();
    expect(screen.queryByTestId('encryption-key')).toBeNull();
  });

  it('key file already shown: no button and no request', () => {
    const fetchMock = mockFetch({});
    render(<KeyPanel keySource="file" keyShown />);
    expect(screen.getByText(/The key was already shown/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Show key once' })).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

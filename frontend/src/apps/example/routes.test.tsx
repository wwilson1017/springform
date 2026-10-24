import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { mockFetch } from '../../testing';
import app from './index';

afterEach(() => vi.unstubAllGlobals());

describe('example routes', () => {
  it('open the widget page at the url the backend links to', async () => {
    // backend/apps/example/entities.py: url_fn=lambda widget_id: f"/example/{widget_id}".
    // Notifications, reminders and search link there, so the app must route it.
    const url = (id: number) => `/example/${id}`;
    mockFetch({
      'GET /api/example/widgets/7': {
        body: { id: 7, name: 'Blue widget', color: '#0000ff', owner_user_id: 1, person_id: null, is_private: false,
          created_at: '2026-10-20T15:00:00Z', updated_at: '2026-10-20T15:00:00Z' },
      },
    });
    render(
      <MemoryRouter initialEntries={[url(7)]}>
        <Routes><Route path="/example/*" element={<app.App />} /></Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByDisplayValue('Blue widget')).toBeTruthy();
  });
});

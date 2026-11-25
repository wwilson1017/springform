import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { mockFetch } from '../../testing';
import CustomFieldSettings from './CustomFieldSettings';
import type { FieldDefinition } from './types';

const field = (id: number, key: string, extra: Partial<FieldDefinition> = {}): FieldDefinition => ({
  id,
  entity_type: 'example.widget',
  key,
  label: key,
  type: 'text',
  options: null,
  required: false,
  position: id * 10,
  archived_at: null,
  owner_app: null,
  retired_at: null,
  created_at: '2026-10-20T15:00:00Z',
  updated_at: '2026-10-20T15:00:00Z',
  ...extra,
});

afterEach(() => vi.unstubAllGlobals());

describe('CustomFieldSettings', () => {
  it("names an app's fields and offers only what the server allows on them", async () => {
    mockFetch({
      'GET /api/core/fields/entity-types': {
        body: [{ type: 'example.widget', label: 'Widget', label_plural: 'Widgets' }],
      },
      'GET /api/core/fields/definitions?entity_type=example.widget&include_archived=true': {
        body: [
          field(1, 'notes'),
          field(2, 'example_finish', { owner_app: 'example' }),
          field(3, 'example_old', { owner_app: 'example', archived_at: 'x', retired_at: 'x' }),
          field(4, 'hidden', { archived_at: 'x' }),
        ],
      },
    });
    render(<CustomFieldSettings />);
    expect(await screen.findByText(/example_finish · from the example app/)).toBeTruthy();
    expect(screen.getAllByRole('button', { name: 'Edit' })).toHaveLength(1); // notes only
    expect(screen.getByRole('button', { name: 'Move example_finish up' })).toBeTruthy();
    expect(screen.getAllByRole('button', { name: 'Archive' })).toHaveLength(2);
    expect(screen.getByText('No longer used by the example app')).toBeTruthy();
    expect(screen.getAllByRole('button', { name: 'Restore' })).toHaveLength(1); // hidden only
  });
});

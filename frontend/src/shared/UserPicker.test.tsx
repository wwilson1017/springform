import { fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { callsTo, mockFetch } from '../testing';
import { UserPicker } from './UserPicker';
import { resetUserNames } from './users';

const FIRST = '/api/core/timeline/mentionable?q=';
const PEOPLE = [{ id: 1, name: 'Ada Admin' }, { id: 2, name: 'Max Member' }];

function Harness({ initial = '', onChange = () => {}, valueName }: { initial?: string; onChange?: (v: string) => void; valueName?: string }) {
  const [value, setValue] = useState(initial);
  return (
    <>
      <label htmlFor="owner">Owner</label>
      <UserPicker id="owner" value={value} valueName={valueName} options={[['', 'Nobody']]}
        onChange={v => { setValue(v); onChange(v); }} />
      <output data-testid="value">{value}</output>
    </>
  );
}

const input = () => screen.getByLabelText('Owner') as HTMLInputElement;

afterEach(() => {
  vi.unstubAllGlobals();
  resetUserNames();
});

describe('UserPicker', () => {
  it("shows the current user's name, from the directory when the caller has no name", async () => {
    mockFetch({ [`GET ${FIRST}`]: { body: PEOPLE } });
    render(<Harness initial="2" />);
    await vi.waitFor(() => expect(input().value).toBe('Max Member'));
  });

  it('takes a name the caller already has without fetching', () => {
    const fetchMock = mockFetch({});
    render(<Harness initial="31" valueName="Zed Late" />);
    expect(input().value).toBe('Zed Late');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('lists the fixed choices and the first people on open, searches as you type, and picks by keyboard', async () => {
    const onChange = vi.fn();
    const fetchMock = mockFetch({
      [`GET ${FIRST}`]: { body: PEOPLE },
      [`GET ${FIRST}max`]: { body: [PEOPLE[1]] },
    });
    render(<Harness onChange={onChange} />);
    expect(input().value).toBe('Nobody');
    fireEvent.focus(input());
    expect(await screen.findByRole('option', { name: 'Ada Admin' })).toBeTruthy();
    expect(screen.getAllByRole('option').map(o => o.textContent)).toEqual(['Nobody', 'Ada Admin', 'Max Member']);

    fireEvent.change(input(), { target: { value: 'max' } });
    await vi.waitFor(() => expect(screen.getAllByRole('option').map(o => o.textContent)).toEqual(['Max Member']));
    expect(callsTo(fetchMock, 'GET', `${FIRST}max`)).toHaveLength(1);
    expect(input().getAttribute('aria-activedescendant')).toBe(screen.getByRole('option', { name: 'Max Member' }).id);
    fireEvent.keyDown(input(), { key: 'Enter' });
    expect(onChange).toHaveBeenCalledWith('2');
    expect(screen.queryByRole('listbox')).toBeNull();
    expect(input().value).toBe('Max Member');
  });

  it('moves with the arrows and closes on Escape without changing the value', async () => {
    const onChange = vi.fn();
    mockFetch({ [`GET ${FIRST}`]: { body: PEOPLE } });
    render(<Harness onChange={onChange} />);
    fireEvent.keyDown(input(), { key: 'ArrowDown' });
    await screen.findByRole('option', { name: 'Ada Admin' });
    fireEvent.keyDown(input(), { key: 'ArrowDown' });
    expect(screen.getByRole('option', { name: 'Ada Admin' }).getAttribute('aria-selected')).toBe('true');
    fireEvent.keyDown(input(), { key: 'Escape' });
    expect(screen.queryByRole('listbox')).toBeNull();
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByTestId('value').textContent).toBe('');
  });

  it("starts the highlight on the current user's row", async () => {
    mockFetch({ [`GET ${FIRST}`]: { body: PEOPLE } });
    render(<Harness initial="2" />);
    fireEvent.focus(input());
    const max = await screen.findByRole('option', { name: 'Max Member' });
    expect(max.getAttribute('aria-selected')).toBe('true');
    fireEvent.keyDown(input(), { key: 'ArrowUp' });
    expect(screen.getByRole('option', { name: 'Ada Admin' }).getAttribute('aria-selected')).toBe('true');
  });

  it('picks a row by click', async () => {
    mockFetch({ [`GET ${FIRST}`]: { body: PEOPLE } });
    render(<Harness initial="2" />);
    fireEvent.click(input());
    fireEvent.click(await screen.findByRole('option', { name: 'Nobody' }));
    expect(screen.getByTestId('value').textContent).toBe('');
    expect(input().value).toBe('Nobody');
  });
});

// @vitest-environment jsdom
//
// "Today" belongs to the LIST, not to the browser looking at it. The server buckets
// due dates in the list's time zone (it comes back with the filters payload), and
// the web app must agree — otherwise a list kept in Tokyo and opened in Chicago
// shows today's work as tomorrow's and yesterday's as today's.
//
// The runner is pinned to America/Chicago (vitest.config.ts). At the instant frozen
// below it is still Aug 1 there and already Aug 2 in Tokyo, so every assertion here
// fails if any date decision falls back to the browser's zone.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { todayTodosMock, createTodoMock } = vi.hoisted(() => ({
  todayTodosMock: vi.fn(),
  createTodoMock: vi.fn(),
}));
vi.mock('./api', () => ({
  todayTodos: todayTodosMock,
  createTodo: createTodoMock,
  updateTodo: vi.fn(),
  listTodos: vi.fn().mockResolvedValue([]),
  listProjects: vi.fn().mockResolvedValue([]),
  getFilters: vi.fn().mockResolvedValue({
    contexts: [], tags: [], status_counts: {}, tz: 'Asia/Tokyo',
  }),
}));

import { TodayPage } from './TodayPage';
import type { Todo } from './types';
import { resetUndoQueue } from './undoQueue';
import { todayStr, zonedNow } from './util';
import { ITEM_EXTRA } from './testFixtures';

// 21:00 on Aug 1 in Chicago; 11:00 on Aug 2 in Tokyo.
const NOW = new Date('2026-08-02T02:00:00Z');

const base: Omit<Todo, 'id' | 'title' | 'due_date'> = { ...ITEM_EXTRA,
  notes: '', project_id: null, project_name: null, context: '', tags: [],
  status: 'next_action', star: false, repeat: '',
  auto_star_on_due: false, source: 'ui',
  created_at: '2026-07-20T12:00:00Z', updated_at: '2026-07-20T12:00:00Z', completed_at: null,
};

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  // Only the clock: the page's fetches still resolve on real microtasks.
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(NOW);
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  resetUndoQueue();
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.useRealTimers();
});

/** The titles under a section heading. */
function section(heading: string): string[] {
  const h2 = [...container.querySelectorAll('h2')].find(h => h.textContent?.trim() === heading);
  return [...(h2?.parentElement?.querySelectorAll('p.break-words') ?? [])]
    .map(p => p.textContent?.trim() ?? '');
}

describe('the list’s time zone decides "today"', () => {
  it('the premise: browser and list are on different calendar dates', () => {
    expect(todayStr(NOW)).toBe('2026-08-01');
    expect(todayStr(NOW, 'Asia/Tokyo')).toBe('2026-08-02');
    // An unknown zone name falls back to the browser's date rather than throwing.
    expect(todayStr(NOW, 'Not/AZone')).toBe('2026-08-01');
  });

  it('zonedNow carries the list’s date in its local fields, for the quick-add parser', () => {
    const d = zonedNow('Asia/Tokyo', NOW);
    expect([d.getFullYear(), d.getMonth() + 1, d.getDate()]).toEqual([2026, 8, 2]);
  });

  it('Today buckets and labels by the list’s date, not the browser’s', async () => {
    todayTodosMock.mockResolvedValue([
      { ...base, id: 1, title: 'due on the 1st', due_date: '2026-08-01' },
      { ...base, id: 2, title: 'due on the 2nd', due_date: '2026-08-02' },
    ]);
    await act(async () => {
      root.render(<MemoryRouter><TodayPage /></MemoryRouter>);
    });
    await act(async () => {}); // the filters payload (and its tz) lands

    // In the browser's zone the 1st would be "Due today" and the 2nd not due at all.
    expect(section('Overdue')).toEqual(['due on the 1st']);
    expect(section('Due today')).toEqual(['due on the 2nd']);
    // The row's own due chip agrees with the section it sits in.
    const row = [...container.querySelectorAll('p.break-words')]
      .find(p => p.textContent?.includes('due on the 2nd'))!.parentElement!;
    expect(row.textContent).toContain('Today');
  });

  it('quick-add "tomorrow" is the day after the LIST’s today', async () => {
    todayTodosMock.mockResolvedValue([]);
    createTodoMock.mockResolvedValue({});
    await act(async () => {
      root.render(<MemoryRouter><TodayPage /></MemoryRouter>);
    });
    await act(async () => {});

    const input = container.querySelector<HTMLInputElement>('input[placeholder^="Add to inbox"]')!;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
    act(() => {
      setter.call(input, 'water the plants tomorrow');
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await act(async () => {
      input.form!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });

    expect(createTodoMock).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'water the plants', due_date: '2026-08-03' }),
    );
  });

  it('Today’s "Time to revisit" uses the list’s date, and an overdue todo is not repeated there', async () => {
    todayTodosMock.mockResolvedValue([
      { ...base, id: 1, title: 'revisit yesterday', due_date: null, revisit_on: '2026-08-01' },
      { ...base, id: 2, title: 'revisit today', due_date: null, revisit_on: '2026-08-02' },
      { ...base, id: 3, title: 'revisit tomorrow', due_date: null, revisit_on: '2026-08-03' },
      { ...base, id: 4, title: 'overdue and revisit', due_date: '2026-08-01', revisit_on: '2026-08-01' },
    ]);
    await act(async () => {
      root.render(<MemoryRouter><TodayPage /></MemoryRouter>);
    });
    await act(async () => {});

    expect(section('Time to revisit')).toEqual(['revisit yesterday', 'revisit today']);
    expect(section('Overdue')).toEqual(['overdue and revisit']);
    expect(container.textContent?.split('overdue and revisit').length).toBe(2); // exactly once
  });
});

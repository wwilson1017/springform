// @vitest-environment jsdom
//
// The server keeps a todo deferred to a future revisit date off the working lists.
// Three pages are record views or project-health checks and must ask for it anyway
// (`include_deferred`), or a project whose next action is merely scheduled to come
// back is flagged as having none. Review reads "stale" from the working list, so the
// server alone decides what is put away. All of it is silent when it breaks.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { listProjectsMock, listTodosMock, getFiltersMock } = vi.hoisted(() => ({
  listProjectsMock: vi.fn(),
  listTodosMock: vi.fn(),
  getFiltersMock: vi.fn(),
}));
vi.mock('./api', () => ({
  listProjects: listProjectsMock,
  listTodos: listTodosMock,
  updateProject: vi.fn(),
  getFilters: getFiltersMock,
  // The Review page's "review due" strip.
  getReviewStatus: vi.fn().mockResolvedValue({ review_due: false, days_since_review: null }),
  markReviewDone: vi.fn(),
  createTodo: vi.fn(),
  updateTodo: vi.fn(),
  createProject: vi.fn(),
  todayTodos: vi.fn().mockResolvedValue([]),
  getCaptureLink: vi.fn(),
  regenerateCaptureLink: vi.fn(),
}));

import { ProjectDetailPage } from './ProjectDetailPage';
import { ProjectsPage } from './ProjectsPage';
import { ReviewPage } from './ReviewPage';
import type { Todo, TodoProject } from './types';
import { ITEM_EXTRA, PROJECT_EXTRA } from './testFixtures';

const PROJECT: TodoProject = { ...PROJECT_EXTRA,
  id: 7, name: 'Lease', notes: '', status: 'active', open_count: 2,
  created_at: '2020-01-01T12:00:00Z', updated_at: '2020-01-01T12:00:00Z',
};
// Both untouched for years, so both are "stale" by age; only one is deferred.
const base: Omit<Todo, 'id' | 'title'> = { ...ITEM_EXTRA,
  notes: '', project_id: null, project_name: null, context: '', tags: [],
  status: 'next_action', star: false, due_date: null, repeat: '',
  auto_star_on_due: false, source: 'ui',
  created_at: '2020-01-01T12:00:00Z', updated_at: '2020-01-01T12:00:00Z', completed_at: null,
};
const FILTERS = { contexts: [], tags: [], status_counts: {}, tz: 'UTC' };
const DEFERRED: Todo = { ...base, id: 1, title: 'ask about the lease', project_id: 7, revisit_on: '2999-01-01' };
const FORGOTTEN: Todo = { ...base, id: 2, title: 'forgotten' };

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  listProjectsMock.mockReset().mockResolvedValue([PROJECT]);
  getFiltersMock.mockReset().mockResolvedValue(FILTERS);
  // What the server does: the deferred todo comes back only when asked for.
  listTodosMock.mockReset().mockImplementation(
    ({ status, include_deferred }: { status?: string; include_deferred?: boolean }) =>
      Promise.resolve(status && status !== 'next_action'
        ? [] : include_deferred ? [DEFERRED, FORGOTTEN] : [FORGOTTEN]),
  );
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.useRealTimers();
});

async function render(path: string) {
  await act(async () => {
    root.render(
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/review" element={<ReviewPage />} />
          <Route path="/projects" element={<ProjectsPage />} />
          <Route path="/projects/:id" element={<ProjectDetailPage />} />
        </Routes>
      </MemoryRouter>,
    );
  });
  await act(async () => {});
}

describe('deferred todos on the record views', () => {
  it('Review: a deferred next action covers its project and is not stale', async () => {
    await render('/review');
    expect(container.textContent).toContain('forgotten');
    expect(container.textContent).not.toContain('ask about the lease');
    expect(container.textContent).toContain('Every active project has a next action.');
  });

  it('Review: takes the server\'s word on what is deferred, with no time zone loaded', async () => {
    // The list is a day ahead of this browser: 23:30 UTC on Aug 8 is already Aug 9 in
    // Kiritimati, so the server's working list holds a todo brought back on the 9th.
    // The page must show it (stale by age), not sort it on the browser's date — and
    // the meta that carries the list's time zone has not arrived at all.
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date('2026-08-08T23:30:00Z'));
    listTodosMock.mockImplementation(({ status }: { status?: string }) =>
      Promise.resolve(status === 'next_action' ? [{ ...DEFERRED, revisit_on: '2026-08-09' }] : []));
    let arrive!: (f: unknown) => void;
    getFiltersMock.mockReturnValue(new Promise(r => { arrive = r; }));

    await render('/review');
    expect(container.textContent).toContain('ask about the lease');
    expect(container.textContent).toContain('Every active project has a next action.');
    await act(async () => { arrive(FILTERS); }); // leave no fetch hanging for the next test
  });

  it('Projects: a project whose next action is deferred is not flagged', async () => {
    await render('/projects');
    expect(listTodosMock).toHaveBeenCalledWith(
      expect.objectContaining({ status: 'next_action', include_deferred: true }));
    expect(container.textContent).toContain('Lease');
    expect(container.textContent).not.toMatch(/no next action/i);
  });

  it("a project's own page shows its deferred todos", async () => {
    await render('/projects/7');
    expect(listTodosMock).toHaveBeenCalledWith(
      expect.objectContaining({ project_id: 7, include_deferred: true }));
    expect(container.textContent).toContain('ask about the lease');
  });
});

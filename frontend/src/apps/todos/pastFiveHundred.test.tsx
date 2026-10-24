// @vitest-environment jsdom
//
// Past 500 next actions, the app used to see only the first page — so the two pages that
// flag a project with no next action had a guard: a full 500-row window proves nothing, so
// flag nobody. The list now arrives whole, and that guard would silence the warning on
// exactly the lists big enough to need it.
//
// No `./api` mock: the pages go through the real `listTodos` to a stubbed `fetch`, so the
// paging itself is under test, and an API call some later change adds to these pages
// gets an empty answer here instead of breaking the mock.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ProjectsPage } from './ProjectsPage';
import { ReviewPage } from './ReviewPage';
import { ITEM_EXTRA, PROJECT_EXTRA } from './testFixtures';

const AT = '2026-09-01T12:00:00Z';
const project = (id: number, name: string) =>
  ({ ...PROJECT_EXTRA, id, name, notes: '', status: 'active', open_count: 1, created_at: AT, updated_at: AT });
// 501 next actions, every one in the first project: the second has none.
const NEXT = Array.from({ length: 501 }, (_, i) => ({ ...ITEM_EXTRA,
  id: i + 1, title: `step ${i + 1}`, notes: '', project_id: 1, project_name: 'Busy', context: '',
  tags: [], status: 'next_action', star: false, due_date: null, repeat: '',
  auto_star_on_due: false, source: 'ui', created_at: AT, updated_at: new Date().toISOString(),
  completed_at: null,
}));

const COUNTS = {
  inbox: 0, next_action: 501, waiting_for: 0, delegated: 0, someday_maybe: 0, done: 0, dropped: 0,
};

let container: HTMLDivElement;
let root: Root;
let asked: string[];

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  asked = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    const { pathname, searchParams: q } = new URL(url, 'http://x');
    let body: unknown = {};
    if (pathname.endsWith('/projects')) body = [project(1, 'Busy'), project(2, 'Stalled')];
    else if (pathname.endsWith('/today')) body = [];
    else if (pathname.endsWith('/filters')) body = { contexts: [], tags: [], status_counts: COUNTS };
    else if (pathname.endsWith('/review')) body = { review_due: false, days_since_review: 0, last_review_at: null };
    else if (pathname.endsWith('/items')) {
      asked.push(`${q.get('status')}@${q.get('offset')}`);
      const from = Number(q.get('offset') ?? 0);
      const rows = q.get('status') === 'next_action' ? NEXT : [];
      body = rows.slice(from, from + Number(q.get('limit')));
    }
    return { ok: true, status: 200, json: async () => body };
  }));
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
});

async function render(path: string) {
  await act(async () => {
    root.render(
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/review" element={<ReviewPage />} />
          <Route path="/projects" element={<ProjectsPage />} />
        </Routes>
      </MemoryRouter>,
    );
  });
  await act(async () => {});
  await act(async () => {});
}

describe('more than 500 next actions', () => {
  it('Projects: still flags the one project that has none', async () => {
    await render('/projects');
    expect(asked).toContain('next_action@500'); // the second page was fetched
    expect(container.textContent!.match(/No next action/g)).toHaveLength(1);
  });

  it('Review: still lists the one project that has none', async () => {
    await render('/review');
    expect(asked).toContain('next_action@500');
    expect(container.textContent).not.toContain('Every active project has a next action.');
    expect(container.textContent).toContain('Stalled');
  });
});

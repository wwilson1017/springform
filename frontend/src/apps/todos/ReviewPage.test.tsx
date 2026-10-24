// @vitest-environment jsdom
//
// The Review page's "review due" line and its Mark review done button.
//
// The line is what makes the weekly review a habit rather than a page nobody opens, so
// what is pinned is that it appears exactly when the server says a review is due, that the
// button clears it with the server's answer rather than an optimistic guess, and that a
// failed save says so instead of quietly leaving the line where it was.
//
// createRoot + React act, following the repo's other component tests — no RTL.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { getReviewStatusMock, markReviewDoneMock } = vi.hoisted(() => ({
  getReviewStatusMock: vi.fn(),
  markReviewDoneMock: vi.fn(),
}));

vi.mock('./api', () => ({
  listTodos: vi.fn().mockResolvedValue([]),
  createTodo: vi.fn(),
  updateTodo: vi.fn(),
  listProjects: vi.fn().mockResolvedValue([]),
  getFilters: vi.fn().mockResolvedValue({ contexts: [], tags: [], status_counts: {} }),
  getReviewStatus: getReviewStatusMock,
  markReviewDone: markReviewDoneMock,
}));

import { ReviewPage } from './ReviewPage';

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  getReviewStatusMock.mockReset();
  markReviewDoneMock.mockReset();
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function mount() {
  await act(async () => {
    root.render(<MemoryRouter><ReviewPage /></MemoryRouter>);
  });
  await act(async () => { await Promise.resolve(); });
}

const text = () => container.textContent ?? '';
const markButton = () =>
  [...container.querySelectorAll('button')].find(b => b.textContent === 'Mark review done');

describe('the review-due line', () => {
  it('says a review is due when none was ever recorded', async () => {
    getReviewStatusMock.mockResolvedValue({ review_due: true, days_since_review: null });
    await mount();
    expect(container.querySelector('[role="status"]')?.textContent)
      .toBe('Review due — none recorded yet');
  });

  it('says how long it has been when one is overdue', async () => {
    getReviewStatusMock.mockResolvedValue({ review_due: true, days_since_review: 12 });
    await mount();
    expect(text()).toContain('Review due — last one 12 days ago');
  });

  it('shows no due line while a review is fresh', async () => {
    getReviewStatusMock.mockResolvedValue({ review_due: false, days_since_review: 1 });
    await mount();
    expect(text()).not.toContain('Review due');
    expect(text()).toContain('Last review yesterday.');
  });

  it('does not invent a review for a new list that is not due for one yet', async () => {
    getReviewStatusMock.mockResolvedValue({ review_due: false, days_since_review: null });
    await mount();
    expect(text()).not.toContain('Review due');
    expect(text()).not.toContain('Last review');
    expect(text()).toContain('No review recorded yet.');
    expect(markButton()).toBeDefined();
  });

  it('marking the review done clears the line with the server answer', async () => {
    getReviewStatusMock.mockResolvedValue({ review_due: true, days_since_review: null });
    markReviewDoneMock.mockResolvedValue({ review_due: false, days_since_review: 0 });
    await mount();
    await act(async () => { markButton()!.click(); });
    expect(markReviewDoneMock).toHaveBeenCalledTimes(1);
    expect(text()).not.toContain('Review due');
    expect(text()).toContain('Last review today.');
  });

  it('a failed save says so and keeps the line', async () => {
    getReviewStatusMock.mockResolvedValue({ review_due: true, days_since_review: 9 });
    markReviewDoneMock.mockRejectedValue(new Error('API error 500'));
    await mount();
    await act(async () => { markButton()!.click(); });
    expect(container.querySelector('[role="alert"]')?.textContent).toBe('Could not save. Try again.');
    expect(text()).toContain('Review due');
  });

  it('renders the lists even when the review clock cannot be read', async () => {
    getReviewStatusMock.mockRejectedValue(new Error('API error 500'));
    await mount();
    expect(markButton()).toBeUndefined();
    expect(text()).toContain('Active projects without a next action');
  });
});

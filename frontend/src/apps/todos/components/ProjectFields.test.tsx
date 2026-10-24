// @vitest-environment jsdom
//
// ProjectDetails re-seeds its draft when the project's saved values move. The case tsc
// cannot see: a save echoing back must not replace text typed since that save was sent.
//
// createRoot + React 19 act, following PeopleInput.test.tsx — no RTL.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

const { updateProjectMock } = vi.hoisted(() => ({ updateProjectMock: vi.fn() }));
vi.mock('../api', () => ({ updateProject: updateProjectMock }));

import { ProjectDetails } from './ProjectFields';
import type { TodoProject } from '../types';

const PROJECT = {
  id: 3, name: 'Kitchen', notes: '', status: 'active', purpose: '', outcome: 'old', area_id: null,
} as unknown as TodoProject;

let container: HTMLDivElement;
let root: Root;
beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  updateProjectMock.mockReset().mockResolvedValue({});
});
afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

const render = (project: TodoProject) =>
  act(async () => { root.render(<ProjectDetails project={project} areas={[]} onSaved={() => {}} />); });
const outcome = () => container.querySelector<HTMLInputElement>('[aria-label="Project outcome"]')!;
const type = (value: string) => act(async () => {
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(outcome(), value);
  outcome().dispatchEvent(new Event('input', { bubbles: true }));
});

it('a save echoing back does not replace text typed since', async () => {
  await render(PROJECT);
  await type('new');
  await act(async () => { outcome().focus(); outcome().blur(); });
  expect(updateProjectMock).toHaveBeenCalledWith(3, { outcome: 'new' });

  await type('new and more');                    // back in the field before the refresh lands
  await render({ ...PROJECT, outcome: 'new' });  // the refresh
  expect(outcome().value).toBe('new and more');
});

it('an untouched field still follows an edit made elsewhere', async () => {
  await render(PROJECT);
  await render({ ...PROJECT, outcome: 'changed elsewhere' });
  expect(outcome().value).toBe('changed elsewhere');
});

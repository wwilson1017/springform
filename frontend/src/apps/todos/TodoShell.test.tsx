// @vitest-environment jsdom
//
// The shell marks the current list — once, with aria-current="page" — in each of
// its two menus: top row and phone bottom bar. The mode comes from a media query,
// so matchMedia is stubbed. It also carries the Mine / Everyone switch on the pages
// that honour it.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('./api', () => ({
  getFilters: vi.fn().mockResolvedValue({ contexts: [], tags: [], status_counts: { inbox: 3 } }),
  listProjects: vi.fn().mockResolvedValue([]),
}));

import { PHONE_QUERY } from './menu';
import { setScope } from './scope';
import { TodoShell, type TodoTab } from './TodoShell';

let container: HTMLDivElement;
let root: Root;

function setScreen(matching: string[]) {
  window.matchMedia = ((q: string) => ({
    matches: matching.includes(q), media: q,
    addEventListener() {}, removeEventListener() {},
  })) as unknown as typeof window.matchMedia;
}

async function render(active: TodoTab, scoped = false) {
  await act(async () => {
    root.render(
      <MemoryRouter>
        <TodoShell active={active} hideQuickAdd scoped={scoped}><p>page body</p></TodoShell>
      </MemoryRouter>,
    );
  });
}

const navLabels = () => [...container.querySelectorAll('nav')].map(n => n.getAttribute('aria-label'));
const current = () => [...container.querySelectorAll('[aria-current="page"]')].map(e => e.textContent);
const more = () => [...container.querySelectorAll('button')].find(b => b.textContent?.startsWith('More'));

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => { root.unmount(); });
  container.remove();
  setScope('mine');
});

describe('TodoShell menus', () => {
  it('top menu: two navs, the current list marked in whichever tier holds it', async () => {
    setScreen([]);
    await render('next');
    expect(navLabels()).toEqual(['Main lists', 'Other lists']);
    expect(current()).toEqual(['To Do']);
    expect(container.textContent).toContain('page body');

    await render('review');
    expect(current()).toEqual(['Review']);
    // jsdom has no layout, so nothing overflows and there is no More.
    expect(more()).toBeUndefined();
  });

  it('top menu: what does not fit moves into More, never the current list', async () => {
    // jsdom has no layout, so give it one: six 50px items in the ruler (the five
    // lists and More) plus 10px of divider, in a slot 170px wide.
    const offset = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetWidth')!;
    Object.defineProperty(HTMLElement.prototype, 'offsetWidth', {
      configurable: true, get(this: HTMLElement) { return this.tagName === 'SPAN' ? 50 : 310; },
    });
    Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, get: () => 170 });
    try {
      setScreen([]);
      await render('review');
      const other = container.querySelector('nav[aria-label="Other lists"]')!;
      expect([...other.querySelectorAll(':scope > a')].map(a => a.textContent)).toEqual(['Areas', 'Review']);
      expect(current()).toEqual(['Review']);
      const button = more()!;
      expect(button.hasAttribute('aria-current')).toBe(false);
      await act(async () => { button.click(); });
      const panel = document.getElementById(button.getAttribute('aria-controls')!)!;
      expect([...panel.querySelectorAll('a')].map(a => a.textContent)).toEqual(['Waiting', 'Someday', 'Done']);

      // A press inside keeps it open; a press or keyboard focus outside closes it.
      await act(async () => { panel.dispatchEvent(new Event('pointerdown', { bubbles: true })); });
      expect(button.getAttribute('aria-expanded')).toBe('true');
      await act(async () => { document.body.dispatchEvent(new Event('pointerdown', { bubbles: true })); });
      expect(button.getAttribute('aria-expanded')).toBe('false');
      await act(async () => { button.click(); });
      await act(async () => { container.querySelector('input')!.focus(); });
      expect(button.getAttribute('aria-expanded')).toBe('false');
    } finally {
      Object.defineProperty(HTMLElement.prototype, 'offsetWidth', offset);
      delete (HTMLElement.prototype as { clientWidth?: number }).clientWidth;
    }
  });

  it('top menu: shows the inbox count and no tagline', async () => {
    setScreen([]);
    await render('inbox');
    expect(current()).toEqual(['Inbox3']);
    expect(container.textContent).not.toContain('Mind like water');
  });

  it('phone: one bottom bar; a secondary list is reached and marked through More', async () => {
    setScreen([PHONE_QUERY]);
    await render('projects');
    expect(navLabels()).toEqual(['Main lists']);
    expect(current()).toEqual(['Projects']);
    expect(more()!.hasAttribute('aria-current')).toBe(false);

    await render('waiting');
    expect(current()).toEqual([]); // the sheet is closed
    const button = more()!;
    expect(button.getAttribute('aria-current')).toBe('true'); // so More carries the marking
    expect(button.getAttribute('aria-expanded')).toBe('false');
    await act(async () => { button.click(); });
    expect(button.getAttribute('aria-expanded')).toBe('true');
    expect(current()).toEqual(['Waiting']);
    const sheet = document.getElementById(button.getAttribute('aria-controls')!)!;
    expect([...sheet.querySelectorAll('a')].map(a => a.textContent))
      .toEqual(['Areas', 'Waiting', 'Someday', 'Review', 'Done']);

    await act(async () => {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    });
    expect(button.getAttribute('aria-expanded')).toBe('false');
  });
});

describe('the Mine / Everyone switch', () => {
  const pressed = () => [...container.querySelectorAll('[aria-label="Whose todos"] button')]
    .map(b => `${b.textContent}:${b.getAttribute('aria-pressed')}`);

  it('shows only on pages that honour it, starting at Mine', async () => {
    setScreen([]);
    await render('today');
    expect(pressed()).toEqual([]);
    await render('inbox', true);
    expect(pressed()).toEqual(['Mine:true', 'Everyone:false']);
  });

  it('switches the scope every list reads, and remembers it', async () => {
    setScreen([]);
    await render('next', true);
    const everyone = [...container.querySelectorAll('button')].find(b => b.textContent === 'Everyone')!;
    await act(async () => { everyone.click(); });
    expect(pressed()).toEqual(['Mine:false', 'Everyone:true']);
    expect(localStorage.getItem('springform.todos.scope')).toBe('all');
  });
});

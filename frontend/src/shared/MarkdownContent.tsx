// Markdown renderer for Guide topics and assistant messages. GitHub-flavoured (tables, task
// lists, strikethrough); no syntax highlighting.
// simplification: fenced code renders unhighlighted; add rehype-highlight plus a theme that
// follows `.dark` if a reader ever needs it.

import type { ComponentPropsWithoutRef } from 'react';
import ReactMarkdown, { type Components } from 'react-markdown';
import { Link } from 'react-router';
import remarkGfm from 'remark-gfm';

import { ACCENT_TEXT, BG_RAISED, INK, INK_MUTE, LINE } from './styles';

const linkStyle = { color: ACCENT_TEXT, textDecoration: 'underline' };

/**
 * The in-app destination a link points at, or null when it leaves this origin. Parsed with
 * `URL` rather than a `startsWith('/')` test on purpose: `//evil.example/x` also starts with a
 * slash and is a protocol-relative link elsewhere, and an assistant message can carry an
 * injected href. A `javascript:` URL resolves to a null origin, so it is never internal
 * (react-markdown's url transform drops those anyway).
 */
function inAppPath(href: string | undefined): string | null {
  if (!href) return null;
  try {
    const url = new URL(href, window.location.origin);
    return url.origin === window.location.origin ? url.pathname + url.search + url.hash : null;
  } catch {
    return null;
  }
}

const components: Components = {
  // An in-app link navigates in this tab through the router; anything else opens a new tab
  // with `noopener noreferrer`.
  a: ({ href, children }: ComponentPropsWithoutRef<'a'>) => {
    const internal = inAppPath(href);
    return internal !== null ? (
      <Link to={internal} style={linkStyle}>{children}</Link>
    ) : (
      <a href={href} target="_blank" rel="noopener noreferrer" style={linkStyle}>{children}</a>
    );
  },
  // Never fetch remote images: the browser would request the URL on render, which injected
  // content could use to leak data in the query string with zero clicks. Show the alt text.
  img: ({ alt }: ComponentPropsWithoutRef<'img'>) => (
    <span style={{ color: INK_MUTE, fontStyle: 'italic' }}>[{alt || 'image'}]</span>
  ),
  p: ({ children }) => <p style={{ margin: '0 0 10px' }}>{children}</p>,
  ul: ({ children }) => <ul style={{ margin: '0 0 10px', paddingLeft: 22, listStyle: 'disc' }}>{children}</ul>,
  ol: ({ children }) => <ol style={{ margin: '0 0 10px', paddingLeft: 22, listStyle: 'decimal' }}>{children}</ol>,
  li: ({ children }) => <li style={{ margin: '3px 0' }}>{children}</li>,
  h1: ({ children }) => <h1 style={{ fontSize: 20, fontWeight: 600, margin: '18px 0 8px' }}>{children}</h1>,
  h2: ({ children }) => <h2 style={{ fontSize: 17, fontWeight: 600, margin: '18px 0 6px' }}>{children}</h2>,
  h3: ({ children }) => <h3 style={{ fontSize: 15, fontWeight: 600, margin: '14px 0 4px' }}>{children}</h3>,
  blockquote: ({ children }) => (
    <blockquote style={{ margin: '0 0 10px', paddingLeft: 12, borderLeft: `3px solid ${LINE}`, color: INK_MUTE }}>
      {children}
    </blockquote>
  ),
  pre: ({ children }) => (
    <pre style={{ background: BG_RAISED, padding: 12, borderRadius: 8, overflowX: 'auto', fontSize: 13, margin: '0 0 10px' }}>
      {children}
    </pre>
  ),
  code: ({ className, children }: ComponentPropsWithoutRef<'code'>) =>
    className || String(children).includes('\n') ? (
      <code className={className}>{children}</code>
    ) : (
      <code style={{ background: BG_RAISED, borderRadius: 4, padding: '1px 5px', fontSize: 13 }}>{children}</code>
    ),
  table: ({ children }) => (
    <div style={{ overflowX: 'auto', margin: '0 0 10px' }}>
      <table style={{ borderCollapse: 'collapse', fontSize: 13 }}>{children}</table>
    </div>
  ),
  th: ({ children }) => (
    <th style={{ border: `1px solid ${LINE}`, padding: '4px 8px', textAlign: 'left', fontWeight: 600 }}>{children}</th>
  ),
  td: ({ children }) => <td style={{ border: `1px solid ${LINE}`, padding: '4px 8px' }}>{children}</td>,
  hr: () => <hr style={{ border: 0, borderTop: `1px solid ${LINE}`, margin: '16px 0' }} />,
};

/** Renders Markdown `content`; must sit inside a router (in-app links use `Link`). */
export function MarkdownContent({ content }: { content: string }) {
  return (
    <div style={{ fontSize: 14, lineHeight: 1.6, color: INK, wordBreak: 'break-word' }}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>{content}</ReactMarkdown>
    </div>
  );
}

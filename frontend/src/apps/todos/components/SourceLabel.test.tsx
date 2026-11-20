import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { SourceLabel } from './SourceLabel';

const text = (html: string) => html.replace(/<[^>]+>/g, '');

describe('SourceLabel', () => {
  it('names the AI tool behind an MCP-made todo', () => {
    const html = renderToStaticMarkup(<SourceLabel todo={{ source: 'agent', source_client: 'ChatGPT' }} />);
    expect(text(html)).toBe('✦ Added via ChatGPT');
    expect(html).toContain('title="Added by ChatGPT"');
  });

  it('says AI when the tool did not name itself', () => {
    expect(text(renderToStaticMarkup(<SourceLabel todo={{ source: 'agent', source_client: null }} />))).toBe(
      '✦ Added by AI',
    );
  });

  it('shows nothing for a todo a person added', () => {
    expect(renderToStaticMarkup(<SourceLabel todo={{ source: 'ui', source_client: 'ChatGPT' }} />)).toBe('');
  });
});

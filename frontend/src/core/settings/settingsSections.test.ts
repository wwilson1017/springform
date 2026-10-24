import { describe, expect, it } from 'vitest';
import type { CoreApp } from '../api/types';
import { settingsSections, visibleCards, visibleSections } from './settingsSections';

const example = { slug: 'example', name: 'Example' } as CoreApp;

describe('settingsSections', () => {
  it('adds one section per app with settings cards, after the core sections', () => {
    const sections = settingsSections([example]);
    expect(sections.map(s => s.id)).toEqual(['workspace', 'apps', 'integrations', 'data', 'mcp_servers', 'example']);
    expect(sections[5].cards.map(c => [c.id, c.adminOnly])).toEqual([['example', true]]);
  });

  it('derives section visibility from card visibility, so members never see an empty section', () => {
    const sections = settingsSections([example]);
    expect(visibleSections(sections, false).map(s => s.id)).toEqual(['workspace', 'apps']);
    expect(visibleSections(sections, true).map(s => s.id)).toEqual(['workspace', 'apps', 'integrations', 'data', 'mcp_servers', 'example']);
    expect(visibleCards(sections[2], false)).toEqual([]);
  });
});

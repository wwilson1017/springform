import { describe, expect, it } from 'vitest';
import type { CoreApp } from '../api/types';
import { settingsSections, visibleCards, visibleSections } from './settingsSections';

const example = { slug: 'example', name: 'Example' } as CoreApp;
// Other core areas add sections of their own; these assertions cover only the ones this folder
// and integrations/ declare, so a new area's settingsCards.ts does not have to edit this test.
const OWN = new Set(['workspace', 'apps', 'integrations', 'data']);
const own = (ids: string[]) => ids.filter(id => OWN.has(id));

describe('settingsSections', () => {
  it('adds one section per app with settings cards, after the core sections', () => {
    const sections = settingsSections([example]);
    const ids = sections.map(s => s.id);
    expect(own(ids)).toEqual(['workspace', 'apps', 'integrations', 'data']);
    expect(ids.at(-1)).toBe('example');
    expect(sections.at(-1)!.cards.map(c => [c.id, c.adminOnly])).toEqual([['example', true]]);
  });

  it('derives section visibility from card visibility, so members never see an empty section', () => {
    const sections = settingsSections([example]);
    expect(own(visibleSections(sections, false).map(s => s.id))).toEqual(['workspace', 'apps']);
    expect(visibleSections(sections, false).map(s => s.id)).not.toContain('example');
    expect(own(visibleSections(sections, true).map(s => s.id))).toEqual(['workspace', 'apps', 'integrations', 'data']);
    expect(visibleCards(sections.find(s => s.id === 'integrations')!, false)).toEqual([]);
  });
});

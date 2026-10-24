import { describe, expect, it } from 'vitest';
import type { CoreApp } from '../api/types';
import { settingsSections, visibleCards, visibleSections, type SettingsSection } from './settingsSections';

const example = { slug: 'example', name: 'Example' } as CoreApp;
// Other core areas add their own sections (auth's Account, Users, Sign-in; MCP; Integrations; Data); these tests are about the
// shell's two and an app's, so they look only at those.
const ids = (sections: SettingsSection[]) => sections.map(s => s.id).filter(id => ['workspace', 'apps', 'example'].includes(id));

describe('settingsSections', () => {
  it('adds one section per app with settings cards, after the core sections', () => {
    const sections = settingsSections([example]);
    expect(ids(sections)).toEqual(['workspace', 'apps', 'example']);
    expect(sections.at(-1)!.id).toBe('example');
    expect(sections.at(-1)!.cards.map(c => [c.id, c.adminOnly])).toEqual([['example', true]]);
  });

  it('derives section visibility from card visibility, so members never see an empty section', () => {
    const sections = settingsSections([example]);
    expect(ids(visibleSections(sections, false))).toEqual(['workspace', 'apps']);
    expect(ids(visibleSections(sections, true))).toEqual(['workspace', 'apps', 'example']);
    // Integrations holds only admin cards, so a member gets no cards and no section.
    const integrations = sections.find(s => s.id === 'integrations')!;
    expect(visibleCards(integrations, false)).toEqual([]);
    expect(visibleSections(sections, false)).not.toContain(integrations);
  });
});

/**
 * The Settings page's information architecture in one place: core sections first, then one
 * section per app that contributes `settings_cards`. ONE declaration decides both "what goes
 * where" and "who may see it".
 *
 * Section visibility is DERIVED from card visibility (a section shows iff one of its cards does),
 * so an all-admin section can never render empty for a member. Core sections come first and the
 * member-visible one leads, so a member's nav is a prefix of an admin's.
 */
import type { ComponentType } from 'react';
import type { CoreApp } from '../api/types';
import { settingsCardsFor } from '../apps/registry';
import { AppsCard } from './AppsCard';
import { WorkspaceCard } from './WorkspaceCard';

export interface SettingsCardDef {
  id: string;
  title: string;
  /** Hidden from members. Mirrors the admin guard on the routes the card drives. */
  adminOnly: boolean;
  Card: ComponentType;
}

export interface SettingsSection {
  /** The URL segment: `/settings/<id>`. Core ids come first; an app's section id is its slug. */
  id: string;
  label: string;
  cards: SettingsCardDef[];
}

const CORE_SECTIONS: SettingsSection[] = [
  { id: 'workspace', label: 'Workspace', cards: [{ id: 'workspace', title: 'Workspace', adminOnly: false, Card: WorkspaceCard }] },
  { id: 'apps', label: 'Apps', cards: [{ id: 'apps', title: 'Apps', adminOnly: true, Card: AppsCard }] },
];

/** Every section for the apps this user receives (GET /api/core/apps), before the role filter. */
export function settingsSections(apps: CoreApp[]): SettingsSection[] {
  const coreIds = new Set(CORE_SECTIONS.map(s => s.id));
  const appSections = apps.flatMap(app => {
    // simplification: an app slug equal to a core section id ('workspace', 'apps') is shadowed by
    // core; add those ids to the backend's reserved slugs if that ever bites.
    if (coreIds.has(app.slug)) return [];
    const cards = settingsCardsFor(app.slug).map(c => ({ id: c.id, title: c.title, adminOnly: c.admin_only, Card: c.Card }));
    return cards.length ? [{ id: app.slug, label: app.name, cards }] : [];
  });
  return [...CORE_SECTIONS, ...appSections];
}

export function visibleCards(section: SettingsSection, isAdmin: boolean): SettingsCardDef[] {
  return section.cards.filter(c => !c.adminOnly || isAdmin);
}

export function visibleSections(sections: SettingsSection[], isAdmin: boolean): SettingsSection[] {
  return sections.filter(s => visibleCards(s, isAdmin).length > 0);
}

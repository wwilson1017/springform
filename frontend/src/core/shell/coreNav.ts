import type { ReactNode } from 'react';

/**
 * Core areas add navigation the way they add Settings cards: `src/core/<area>/nav.tsx`
 * default-exports `CoreNavItem[]`. `primary` items sit in the header nav between the directory
 * links and the apps; `menu` items go in the user menu and the mobile drawer. Nobody edits
 * Layout.tsx to add a link. The glob is eager, so a nav module holds only data and icons.
 */
export interface CoreNavItem {
  to: string;
  label: string;
  /** An icon element, sized 18. */
  icon: ReactNode;
  placement: 'primary' | 'menu';
  adminOnly?: boolean;
  /** Position among items of the same placement; lower first, default 100. */
  order?: number;
}

const ITEMS: CoreNavItem[] = Object.values(
  import.meta.glob<CoreNavItem[]>('../*/nav.tsx', { eager: true, import: 'default' }),
).flat().sort((a, b) => (a.order ?? 100) - (b.order ?? 100));

export function coreNavItems(placement: CoreNavItem['placement'], isAdmin: boolean): CoreNavItem[] {
  return ITEMS.filter(i => i.placement === placement && (!i.adminOnly || isAdmin));
}

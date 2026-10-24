import { Suspense, useState } from 'react';
import { Link, NavLink, Outlet, useLocation } from 'react-router';
import { AppIcon, IconBuilding, IconHome, IconMenu, IconSliders, IconUsers } from '../../shared/icons';
import { MobileMenuDrawer, type DrawerItem } from '../../shared/MobileMenuDrawer';
import { useIsMobile } from '../../shared/useIsMobile';
import { useCoreApps } from '../apps/CoreAppsContext';
import { navItems } from '../apps/registry';
import { useAuth } from '../auth/AuthContext';
import BootFallback from '../components/BootFallback';
import ChunkErrorBoundary from '../components/ChunkErrorBoundary';
import { NotificationBell } from '../records/NotificationBell';
import { useWorkspace } from '../settings/useWorkspace';
import { coreNavItems } from './coreNav';
import { ThemeToggle } from './ThemeToggle';
import { UserMenu } from './UserMenu';

/** The signed-in frame: header (nav, theme, notifications slot, user menu) over the routed page. */
export function Layout() {
  const { user, isAdmin, signOut } = useAuth();
  const { apps } = useCoreApps();
  const isMobile = useIsMobile();
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const workspace = useWorkspace();

  // App nav for the apps this user receives. Hiding an app removes its nav for members only
  // (the server does not send them hidden apps; the filter holds if it ever does).
  const shown = new Set((apps ?? []).filter(a => !a.hidden || isAdmin).map(a => a.slug));
  const nav: DrawerItem[] = [
    { to: '/', label: 'Home', icon: <IconHome size={18} aria-hidden /> },
    { to: '/people', label: 'People', icon: <IconUsers size={18} aria-hidden /> },
    { to: '/organizations', label: 'Organizations', icon: <IconBuilding size={18} aria-hidden /> },
    ...coreNavItems('primary', isAdmin),
    ...navItems().filter(n => shown.has(n.slug))
      .map(n => ({ to: n.to, label: n.label, icon: <AppIcon name={n.icon} size={18} aria-hidden /> })),
  ];
  // Core pages that live behind the user menu (and in the drawer), not in the header.
  const menu: DrawerItem[] = coreNavItems('menu', isAdmin);

  return (
    <div className="flex min-h-svh flex-col">
      <header className="flex h-13 shrink-0 items-center gap-3 border-b border-sf-line px-4 md:px-7">
        {isMobile && (
          <button type="button" aria-label="Open menu" onClick={() => setMenuOpen(true)}
            className="flex cursor-pointer border-0 bg-transparent p-1 text-sf-ink-mute">
            <IconMenu aria-hidden />
          </button>
        )}
        <Link to="/" className="font-display text-lg font-medium text-sf-ink no-underline">{workspace?.name}</Link>
        {!isMobile && (
          <nav className="ml-4 flex gap-1">
            {nav.map(item => (
              <NavLink key={item.to} to={item.to} end={item.to === '/'}
                className={({ isActive }) => `border-b-2 px-3 py-1.5 text-sm no-underline ${
                  isActive ? 'border-sf-accent text-sf-ink' : 'border-transparent text-sf-ink-soft hover:text-sf-ink'}`}>
                {item.label}
              </NavLink>
            ))}
          </nav>
        )}
        <div className="flex-1" />
        <ThemeToggle />
        <NotificationBell />
        {!isMobile && user && <UserMenu user={user} items={menu} onSignOut={() => void signOut()} />}
      </header>
      {menuOpen && (
        <MobileMenuDrawer items={[...nav, ...menu, { to: '/settings', label: 'Settings', icon: <IconSliders size={18} aria-hidden /> }]}
          onClose={() => setMenuOpen(false)} onSignOut={() => void signOut()} />
      )}
      <main className="flex-1">
        <ChunkErrorBoundary scope="route" resetKey={location.pathname}>
          <Suspense fallback={<BootFallback variant="panel" />}>
            <Outlet />
          </Suspense>
        </ChunkErrorBoundary>
      </main>
    </div>
  );
}

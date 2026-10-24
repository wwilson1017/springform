import { Suspense } from 'react';
import { Navigate, NavLink, useParams } from 'react-router';
import { useCoreApps } from '../apps/CoreAppsContext';
import { useAuth } from '../auth/AuthContext';
import { RequireAdmin } from '../auth/guards';
import BootFallback from '../components/BootFallback';
import ChunkErrorBoundary from '../components/ChunkErrorBoundary';
import { settingsSections, visibleCards, visibleSections, type SettingsSection } from './settingsSections';

/**
 * `/settings/<section>`. Unknown sections fall back to the first visible one rather than 404ing;
 * an all-admin section sits behind RequireAdmin, so a member's deep link lands on /settings.
 */
export function SettingsPage() {
  const { isAdmin } = useAuth();
  const { apps } = useCoreApps();
  const sectionId = (useParams()['*'] ?? '').split('/')[0];

  if (!apps) return <BootFallback variant="panel" />;
  const all = settingsSections(apps);
  const visible = visibleSections(all, isAdmin);
  const section = all.find(s => s.id === sectionId);
  if (!section) return <Navigate to={`/settings/${visible[0].id}`} replace />;
  const adminOnly = section.cards.every(c => c.adminOnly);

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6 px-4 py-8 md:flex-row md:px-8">
      <nav aria-label="Settings sections" className="flex shrink-0 gap-1 overflow-x-auto md:w-48 md:flex-col">
        {visible.map(s => (
          <NavLink key={s.id} to={`/settings/${s.id}`}
            className={({ isActive }) => `whitespace-nowrap rounded px-3 py-2 text-sm no-underline ${
              isActive ? 'bg-sf-raised text-sf-ink' : 'text-sf-ink-soft hover:bg-sf-hover'}`}>
            {s.label}
          </NavLink>
        ))}
      </nav>
      <div className="min-w-0 flex-1">
        {adminOnly
          ? <RequireAdmin fallback="/settings"><SectionCards section={section} isAdmin={isAdmin} /></RequireAdmin>
          : <SectionCards section={section} isAdmin={isAdmin} />}
      </div>
    </div>
  );
}

function SectionCards({ section, isAdmin }: { section: SettingsSection; isAdmin: boolean }) {
  return (
    <div className="flex flex-col gap-4">
      {visibleCards(section, isAdmin).map(({ id, title, Card }) => (
        <section key={id} aria-labelledby={`card-${section.id}-${id}`} className="rounded-lg border border-sf-line-strong bg-sf-card p-5">
          <h2 id={`card-${section.id}-${id}`} className="m-0 mb-4 font-display text-base font-medium text-sf-ink">{title}</h2>
          {/* App cards are lazy and non-essential: a failure stays inside the card. */}
          <ChunkErrorBoundary scope="panel">
            <Suspense fallback={<BootFallback variant="panel" />}>
              <Card />
            </Suspense>
          </ChunkErrorBoundary>
        </section>
      ))}
    </div>
  );
}

import { NavLink } from 'react-router';

const TABS = [
  { to: '/crm', label: 'Dashboard', end: true },
  { to: '/crm/deals', label: 'Pipeline', end: false },
  { to: '/crm/today', label: 'Today', end: true },
  { to: '/crm/analytics', label: 'Analytics', end: true },
  { to: '/crm/touches', label: 'Touches', end: false },
  { to: '/crm/stale', label: 'Stale', end: true },
  { to: '/crm/import', label: 'Import', end: true },
];

/**
 * The CRM's own tabs, under the shell header; scrolls sideways on a phone. Paths are absolute:
 * inside Root's `/crm/*` splat a relative link resolves against the whole URL, so `deals` seen
 * from `/crm/deals` would point at `/crm/deals/deals`.
 */
export function CrmNav() {
  return (
    <nav aria-label="CRM" className="overflow-x-auto border-b border-sf-line px-4 md:px-7">
      <ul className="m-0 flex list-none gap-1 p-0">
        {TABS.map(t => (
          <li key={t.label}>
            <NavLink to={t.to} end={t.end}
              className={({ isActive }) => `block border-b-2 px-3 py-2.5 text-sm whitespace-nowrap no-underline ${
                isActive ? 'border-sf-accent text-sf-ink' : 'border-transparent text-sf-ink-mute hover:text-sf-ink'}`}>
              {t.label}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}

import { useAuth } from '../auth/AuthContext';

/** Install name and timezone. Read-only until the workspace settings endpoint lands. */
export function WorkspaceCard() {
  const { user } = useAuth();
  const rows: Array<[string, string]> = [
    ['Install name', 'Springform'],
    ['Timezone', user?.tz || Intl.DateTimeFormat().resolvedOptions().timeZone],
  ];
  return (
    <div>
      <dl className="m-0 grid grid-cols-[max-content_1fr] gap-x-6 gap-y-2 text-sm">
        {rows.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-sf-ink-dim">{k}</dt>
            <dd className="m-0 text-sf-ink">{v}</dd>
          </div>
        ))}
      </dl>
      <p className="mb-0 mt-4 text-xs text-sf-ink-dim">Read-only for now: saving these arrives in the next wave.</p>
    </div>
  );
}

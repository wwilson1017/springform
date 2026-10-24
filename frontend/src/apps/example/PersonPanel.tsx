import { Link } from 'react-router';
import type { RecordPanelProps } from '../../core/apps/types';
import { useJson } from '../../core/api/useJson';
import { LoadError } from '../../shared/LoadError';
import { widgetsUrl, type Widget } from './api';

/** Shown on a person's page (`core.person`): the widgets linked to that person. */
export default function PersonWidgetsPanel({ entityId }: RecordPanelProps) {
  const { data: widgets, error, reload } = useJson<Widget[]>(widgetsUrl(entityId));
  if (error) return <LoadError label="Couldn't load widgets" onRetry={reload} compact />;
  if (!widgets) return <p className="m-0 text-sm text-sf-ink-dim">Loading…</p>;
  if (widgets.length === 0) return <p className="m-0 text-sm text-sf-ink-dim">No widgets for this person.</p>;
  return (
    <ul className="m-0 list-none p-0 text-sm">
      {widgets.map(w => (
        <li key={w.id} className="py-1"><Link to={`/example/${w.id}`} className="text-sf-accent-text">{w.name}</Link></li>
      ))}
    </ul>
  );
}

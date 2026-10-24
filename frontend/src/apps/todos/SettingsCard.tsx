import { useState } from 'react';
import { putJson } from '../../core/api/client';
import { useJson } from '../../core/api/useJson';
import { useAuth } from '../../core/auth/AuthContext';
import { LoadError } from '../../shared/LoadError';
import { toast } from '../../shared/toast';
import { API } from './api';
import type { TodoFilters, Visibility } from './types';

const KEY = 'todos.default_visibility';

const LABEL: Record<Visibility, string> = {
  private: 'Only the person who adds it',
  team: 'The whole team',
};

/** Settings → Todos: who a new todo, project or area is visible to when its maker does not say.
 *  Everyone reads it (from /filters, since members cannot read settings); admins change it. */
export default function TodosSettingsCard() {
  const { isAdmin } = useAuth();
  const { data, error, reload, setData } = useJson<TodoFilters>(`${API}/filters`);
  const [busy, setBusy] = useState(false);

  if (error) return <LoadError label="Couldn't load the Todos settings" onRetry={reload} compact />;
  if (!data) return <p className="m-0 text-sm text-sf-ink-dim">Loading…</p>;
  const current = data.default_visibility;

  async function choose(value: Visibility) {
    if (value === current || !data) return;
    setBusy(true);
    try {
      await putJson('/api/core/settings', { values: { [KEY]: value } });
      setData({ ...data, default_visibility: value });
      toast.success('Saved.');
    } catch {
      toast.error("Couldn't save the default.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-3 text-sm text-sf-ink-mute">
      <p className="m-0">
        New to-dos, projects and areas are visible to: <strong className="text-sf-ink">{LABEL[current]}</strong>.
        Whoever adds one can still pick either; a team to-do can be seen and edited by every member.
      </p>
      {isAdmin ? (
        <div role="radiogroup" aria-label="Default visibility" className="flex flex-wrap gap-2">
          {(['private', 'team'] as const).map(v => (
            <button key={v} type="button" role="radio" aria-checked={current === v} disabled={busy}
              onClick={() => void choose(v)}
              className={`cursor-pointer rounded-md border px-3 py-1.5 text-sm disabled:opacity-50 ${
                current === v ? 'border-sf-accent bg-sf-accent-soft text-sf-ink' : 'border-sf-line-strong bg-sf-card text-sf-ink-soft hover:bg-sf-hover'}`}>
              {LABEL[v]}
            </button>
          ))}
        </div>
      ) : (
        <p className="m-0 text-xs text-sf-ink-dim">An admin can change this.</p>
      )}
    </div>
  );
}

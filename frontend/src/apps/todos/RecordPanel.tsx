import { useState } from 'react';
import { useNavigate } from 'react-router';
import type { RecordPanelProps } from '../../core/apps/types';
import { useAuth } from '../../core/auth/AuthContext';
import { LoadError } from '../../shared/LoadError';
import { toast } from '../../shared/toast';
import { completeTodo, todosForRecord, updateTodo } from './api';
import { QuickAdd } from './components/QuickAdd';
import { TodoRow } from './components/TodoRow';
import { apiErrorMessage } from './errors';
import { useTodos } from './hooks';
import { MeContext } from './me';
import { todoPath } from './menu';
import type { Todo } from './types';
import { useTodoMeta } from './useTodoMeta';

/** The Todos panel on a person's or organization's page (`recordPanels` in contributions.ts):
 *  the team's todos and the viewer's private ones linked to the record, and a quick add that
 *  links what it adds. Core renders it outside the Todos App, so it provides `me` itself and
 *  reports failures through the core toast. */
export default function TodosRecordPanel(props: RecordPanelProps) {
  const { user, isAdmin } = useAuth();
  return (
    <MeContext.Provider value={{ id: user?.id ?? null, isAdmin }}>
      <Panel {...props} />
    </MeContext.Provider>
  );
}

function Panel({ entityType, entityId }: RecordPanelProps) {
  const [includeDone, setIncludeDone] = useState(false);
  const { todos, failed, reload } = useTodos(
    () => todosForRecord(entityType, entityId, includeDone), `${entityType}:${entityId}:${includeDone}`);
  useTodoMeta(); // the time zone, default visibility and projects the rows and quick add read
  const navigate = useNavigate();

  const write = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
    } catch (e) {
      toast.error(apiErrorMessage(e, "Couldn't update the todo."));
    }
    reload();
  };
  // Completing goes through /complete, so a repeating todo's next occurrence appears here too.
  const toggleDone = (t: Todo) => write(() => t.status === 'done' ? updateTodo(t.id, { status: 'next_action' }) : completeTodo(t.id));
  const toggleStar = (t: Todo) => write(() => updateTodo(t.id, { star: !t.star }));

  return (
    <div className="flex flex-col gap-3">
      <QuickAdd link={{ entity_type: entityType, entity_id: entityId }} onAdded={reload} placeholder="Add a to-do for this record" />
      {failed ? <LoadError label="Couldn't load to-dos" onRetry={reload} compact />
        : !todos ? <p className="m-0 text-sm text-sf-ink-dim">Loading…</p>
        : todos.length === 0 ? <p className="m-0 text-sm text-sf-ink-dim">{includeDone ? 'No to-dos for this record.' : 'No open to-dos for this record.'}</p>
        : (
          <div className="flex flex-col gap-2">
            {todos.map(t => (
              <TodoRow key={t.id} todo={t} showStatus={includeDone} onToggleDone={t => void toggleDone(t)}
                       onToggleStar={t => void toggleStar(t)} onEdit={t => navigate(todoPath(`/items/${t.id}`))} />
            ))}
          </div>
        )}
      <label className="flex items-center gap-2 text-xs text-sf-ink-dim">
        <input type="checkbox" checked={includeDone} onChange={e => setIncludeDone(e.target.checked)} className="accent-sf-accent" />
        Show done
      </label>
    </div>
  );
}

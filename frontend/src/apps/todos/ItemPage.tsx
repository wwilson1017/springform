import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import { ApiError } from '../../core/api/client';
import { useJson } from '../../core/api/useJson';
import { Attachments } from '../../core/records/Attachments';
import { Timeline } from '../../core/records/Timeline';
import { confirmDialog } from '../../shared/confirm';
import { API, deleteTodo } from './api';
import { TodoEditSheet } from './components/TodoEditSheet';
import { apiErrorMessage } from './errors';
import { useFeedReload, useRowActions } from './hooks';
import { useMe } from './me';
import { todoPath } from './menu';
import { toast } from './toast';
import { LoadFailed, LoadingRows, TodoShell } from './TodoShell';
import type { Todo } from './types';
import { useTodoMeta } from './useTodoMeta';

/** The timeline and attachments entity type for a todo (backend entities.py). */
export const TODO_ENTITY = 'todos.item';

/** Where a linked record lives in the core shell. */
const RECORD_PATHS: Record<string, string> = { 'core.person': '/people', 'core.organization': '/organizations' };

/** A todo's own page (`items/:id`): every field, then its notes thread, files and history, which
 *  core keeps for any record and authorizes by the todo's own rule. */
export function ItemPage() {
  const { id } = useParams();
  const { data: todo, error, reload } = useJson<Todo>(`${API}/items/${Number(id)}`);
  const { projects, filters } = useTodoMeta();
  const { toggleDone } = useRowActions(reload);
  const me = useMe();
  const navigate = useNavigate();
  const [deleting, setDeleting] = useState(false);
  useFeedReload(reload);

  if (error instanceof ApiError && error.status === 404) {
    return (
      <TodoShell active="item" hideQuickAdd>
        <p className="text-sf-ink-dim">This todo doesn't exist, or you can't see it.</p>
      </TodoShell>
    );
  }

  const remove = async () => {
    if (!todo || !await confirmDialog({
      title: 'Delete this todo?',
      message: `“${todo.title}” goes for good, with its notes and files. To keep it out of the way instead, set its status to Dropped.`,
      confirmLabel: 'Delete', danger: true,
    })) return;
    setDeleting(true);
    try {
      await deleteTodo(todo.id);
      navigate(todoPath(''));
    } catch (e) {
      toast.error(apiErrorMessage(e, "Couldn't delete the todo."));
      setDeleting(false);
    }
  };

  const recordPath = todo?.entity_type && todo.entity_id ? RECORD_PATHS[todo.entity_type] : undefined;
  const canDelete = todo && (todo.owner_user_id === me.id || me.isAdmin);

  return (
    <TodoShell active="item" hideQuickAdd>
      {error && <LoadFailed retry={reload} />}
      {!error && !todo && <LoadingRows />}
      {todo && (
        <>
          <div className="mb-4 flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2 text-sm text-sf-ink">
              <input type="checkbox" checked={todo.status === 'done'} onChange={() => void toggleDone(todo)}
                     className="h-5 w-5 accent-sf-green" />
              {todo.status === 'done' ? 'Done' : 'Mark done'}
            </label>
            {recordPath && (
              <Link to={`${recordPath}/${todo.entity_id}`} className="text-sm text-sf-accent-text">
                Open the linked record
              </Link>
            )}
            {canDelete && (
              <button type="button" onClick={() => void remove()} disabled={deleting}
                      className="ml-auto cursor-pointer rounded-lg border border-sf-line-strong bg-transparent px-3 py-1.5 text-sm text-sf-red-text hover:bg-sf-hover disabled:opacity-50">
                Delete
              </button>
            )}
          </div>
          {/* key: a fresh form whenever the saved row changes (a save, a sync, a completion). */}
          <TodoEditSheet key={`${todo.id}:${todo.rev}`} asPage todo={todo} projects={projects}
                         contexts={filters?.contexts ?? []} onClose={() => {}} onSaved={reload} />
          <div className="mt-8 grid gap-8 md:grid-cols-2">
            <section>
              <h2 className="m-0 mb-3 font-display text-base font-medium text-sf-ink">Notes and history</h2>
              <Timeline key={todo.rev} entityType={TODO_ENTITY} entityId={todo.id} />
            </section>
            <section>
              <h2 className="m-0 mb-3 font-display text-base font-medium text-sf-ink">Files</h2>
              <Attachments entityType={TODO_ENTITY} entityId={todo.id} />
            </section>
          </div>
        </>
      )}
    </TodoShell>
  );
}

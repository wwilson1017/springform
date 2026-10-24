import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router';
import { apiErrorMessage } from './errors';
import { InlineTitle } from './lib/inline-edit';
import { createArea, listAreas, listProjects, listTodos, updateArea } from './api';
import { TodoEditSheet } from './components/TodoEditSheet';
import { TodoRow } from './components/TodoRow';
import { SharingFields } from './components/Sharing';
import { memberName } from './util';
import { useFeedReload, useRowActions, useTodosChanged } from './hooks';
import { todoPath } from './menu';
import { EmptyState, LoadFailed, LoadingRows, TodoShell } from './TodoShell';
import type { Todo, TodoArea, TodoProject, Visibility } from './types';
import { useTodoMeta } from './useTodoMeta';

const h3Cls = 'mb-2 mt-4 text-xs font-display font-bold uppercase tracking-wide text-sf-ink-dim';
const smallBtnCls =
  'shrink-0 rounded-lg border border-sf-line-strong px-2.5 py-1.5 text-xs font-display text-sf-ink-dim hover:bg-sf-hover hover:text-sf-ink';

/** Areas of focus — the standing parts of a life or job (Health, Family, the day
 *  job). Each shows what is live under it: active projects, next actions and
 *  someday items. A todo in a project sits under its project's area unless it
 *  has its own. Nothing is deleted: an area is archived and can be restored. */
export function AreasPage() {
  const [areas, setAreas] = useState<TodoArea[] | null>(null);
  const [projects, setProjects] = useState<TodoProject[]>([]);
  const [todos, setTodos] = useState<Todo[]>([]);
  const [failed, setFailed] = useState(false);
  const [name, setName] = useState('');
  const [visibilityPick, setVisibility] = useState<Visibility | null>(null);
  const [error, setError] = useState('');
  const [editTodo, setEditTodo] = useState<Todo | null>(null);
  const meta = useTodoMeta();

  const [loadSeq, setLoadSeq] = useState(0);
  const reload = useCallback(() => { setLoadSeq(s => s + 1); }, []);
  useTodosChanged(reload);
  useFeedReload(reload);
  const members = meta.filters?.members ?? [];
  const newVisibility = visibilityPick ?? meta.filters?.default_visibility ?? 'private';

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      listAreas(),
      listProjects('active'),
      listTodos({ status: 'next_action', limit: 500 }),
      listTodos({ status: 'someday_maybe', limit: 500 }),
    ]).then(([a, p, next, someday]) => {
      if (cancelled) return;
      setAreas(a);
      setProjects(p);
      setTodos([...next, ...someday]);
      setFailed(false);
    }).catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; };
  }, [loadSeq]);

  const { toggleDone, toggleStar, after } = useRowActions(reload);

  /** One area write. Resolving false keeps an inline editor open on what was typed. */
  const write = async (run: () => Promise<unknown>): Promise<boolean> => {
    setError('');
    try {
      await run();
      after(); // reloads this page and the shared meta the area pickers read
      return true;
    } catch (e) {
      setError(apiErrorMessage(e, 'Could not save. Your change was not stored.'));
      return false;
    }
  };

  const add = async () => {
    if (!name.trim()) return;
    if (await write(() => createArea({ name: name.trim(), visibility: newVisibility }))) setName('');
  };

  const rows = (items: Todo[]) => (
    <div className="space-y-2">
      {items.map(t => (
        <TodoRow key={t.id} todo={t} onToggleDone={toggleDone}
                 onToggleStar={toggleStar} onEdit={setEditTodo} />
      ))}
    </div>
  );

  const active = (areas ?? []).filter(a => a.status === 'active');
  const archived = (areas ?? []).filter(a => a.status === 'dropped');

  return (
    <TodoShell active="areas" onAdded={reload}>
      <form onSubmit={e => { e.preventDefault(); void add(); }} className="mb-4 flex gap-2">
        <input
          value={name}
          onChange={e => setName(e.target.value)}
          placeholder="Add an area of focus — Health, Family, Finances…"
          aria-label="New area name"
          className="min-w-0 flex-1 rounded-lg border border-sf-line-strong bg-sf-card px-3 py-2 text-base sm:text-sm text-sf-ink placeholder:text-sf-ink-dim focus:border-sf-accent focus:outline-none"
        />
        <select value={newVisibility} onChange={e => setVisibility(e.target.value as Visibility)}
                aria-label="Who can see the new area"
                className="shrink-0 rounded-lg border border-sf-line-strong bg-sf-card px-2 py-2 text-sm text-sf-ink focus:border-sf-accent focus:outline-none">
          <option value="private">Only me</option>
          <option value="team">Team</option>
        </select>
        <button type="submit" disabled={!name.trim()}
                className="shrink-0 rounded-lg bg-sf-accent px-4 py-2 text-sm font-display text-sf-accent-ink hover:bg-sf-accent-dark disabled:opacity-40">
          Add
        </button>
      </form>
      {error && <p role="alert" className="mb-3 text-sm text-sf-red-text">{error}</p>}

      {failed && <LoadFailed retry={reload} />}
      {!failed && areas === null && <LoadingRows />}
      {!failed && areas !== null && areas.length === 0 && (
        <EmptyState
          title="No areas yet"
          hint="An area is a part of your life you keep up rather than finish. Add one, then pick it on a project or a todo."
        />
      )}

      <div className="space-y-4">
        {active.map(area => {
          const areaProjects = projects.filter(p => p.area_id === area.id);
          const mine = todos.filter(t => t.effective_area_id === area.id);
          const next = mine.filter(t => t.status === 'next_action');
          const someday = mine.filter(t => t.status === 'someday_maybe');
          return (
            <section key={area.id} data-area={area.name}
                     className="rounded-xl border border-sf-line bg-sf-card p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 grow">
                  <h2 className="font-display text-lg font-bold text-sf-ink">
                    <InlineTitle
                      title={area.name}
                      label="Area name"
                      onSave={value => write(() => updateArea(area.id, { name: value }))}
                      onCancel={() => setError('')}
                      className="-ml-1 font-display text-lg font-bold text-sf-ink"
                    />
                  </h2>
                  <InlineTitle
                    title={area.notes}
                    label="Area notes"
                    variant="body"
                    placeholder="Add notes…"
                    onSave={value => write(() => updateArea(area.id, { notes: value }))}
                    onCancel={() => setError('')}
                    className="-ml-1 whitespace-pre-wrap text-sm text-sf-ink-dim"
                  />
                </div>
                <button type="button" className={smallBtnCls}
                        title="Archive this area. Its projects and todos stay where they are."
                        onClick={() => void write(() => updateArea(area.id, { status: 'dropped' }))}>
                  Archive
                </button>
              </div>

              <div className="mt-3">
                <SharingFields idPrefix={`area-${area.id}`} visibility={area.visibility} assignee={area.assignee_user_id}
                               ownerId={area.owner_user_id} members={members}
                               onChange={p => void write(() => updateArea(area.id, p))} />
                <p className="mt-1 mb-0 text-xs text-sf-ink-dim">Owner: {memberName(members, area.owner_user_id)}</p>
              </div>

              {areaProjects.length + mine.length === 0 && (
                <p className="mt-3 text-sm text-sf-ink-dim">
                  Nothing live here yet — pick this area on a project or a todo.
                </p>
              )}
              {areaProjects.length > 0 && (
                <>
                  <h3 className={h3Cls}>Projects</h3>
                  <ul className="space-y-1">
                    {areaProjects.map(p => (
                      <li key={p.id}>
                        <Link to={todoPath(`/projects/${p.id}`)}
                              className="flex items-center justify-between gap-2 rounded-lg border border-sf-line px-3 py-2 text-sm text-sf-ink hover:border-sf-accent/40">
                          <span className="min-w-0 break-words">{p.name}</span>
                          <span className="shrink-0 rounded-full bg-sf-bg px-2 py-0.5 text-xs text-sf-ink-dim">
                            {p.open_count} open
                          </span>
                        </Link>
                      </li>
                    ))}
                  </ul>
                </>
              )}
              {next.length > 0 && <><h3 className={h3Cls}>Next actions</h3>{rows(next)}</>}
              {someday.length > 0 && <><h3 className={h3Cls}>Someday</h3>{rows(someday)}</>}
            </section>
          );
        })}
      </div>

      {archived.length > 0 && (
        <section className="mt-6">
          <h2 className={h3Cls}>Archived areas</h2>
          <ul className="space-y-1">
            {archived.map(area => (
              <li key={area.id}
                  className="flex items-center justify-between gap-2 rounded-lg border border-sf-line bg-sf-card px-3 py-2 text-sm text-sf-ink-dim">
                <span className="min-w-0 break-words">{area.name}</span>
                <button type="button" className={smallBtnCls}
                        onClick={() => void write(() => updateArea(area.id, { status: 'active' }))}>
                  Restore
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {editTodo && (
        <TodoEditSheet
          todo={editTodo}
          projects={meta.projects}
          contexts={meta.filters?.contexts ?? []}
          onClose={() => setEditTodo(null)}
          onSaved={after}
        />
      )}
    </TodoShell>
  );
}

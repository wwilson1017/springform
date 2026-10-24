import { useMemo, useState } from 'react';
import { SearchFilterBar } from './lib/search';
import { TodoEditSheet } from './components/TodoEditSheet';
import { useRowActions, useStatusList } from './hooks';
import { useScope } from './scope';
import { EmptyState, LoadFailed, LoadingRows, TodoShell } from './TodoShell';
import type { Todo } from './types';
import { useTodoMeta } from './useTodoMeta';
import { formatAge, matchesFilter } from './util';

/** Waiting-for + delegated, each row carrying its context and its age — the
 * number that tells you a follow-up is overdue. One-click reactivate to Next.
 * These rows are hand-built rather than TodoRow (they carry the age chip and
 * the reactivate button instead of a done checkbox), which is why the context
 * chip TodoRow already renders has to be repeated here.
 *
 * Two fixed sections fed by two separate fetches, filtered through the shared
 * `SearchFilterBar`, page-owns-state. */
export function WaitingPage() {
  const scope = useScope();
  const { todos: waiting, failed: f1, reload: r1 } = useStatusList('waiting_for', scope);
  const { todos: delegated, failed: f2, reload: r2 } = useStatusList('delegated', scope);
  const reload = () => { r1(); r2(); };
  const { setStatus, after } = useRowActions(reload);
  const { projects, filters } = useTodoMeta();
  const [search, setSearch] = useState('');
  const [editTodo, setEditTodo] = useState<Todo | null>(null);

  const failed = f1 || f2;
  const loading = waiting === null || delegated === null;

  const memoWaiting = useMemo(
    () => (waiting ?? []).filter(t => matchesFilter(t, search)), [waiting, search]);
  const memoDelegated = useMemo(
    () => (delegated ?? []).filter(t => matchesFilter(t, search)), [delegated, search]);

  const section = (title: string, items: Todo[]) => (
    <section>
      <h2 className="mb-2 text-xs font-display font-bold uppercase tracking-wide text-sf-ink-dim">
        {title} ({items.length})
      </h2>
      {items.length === 0 ? (
        <p className="text-sm text-sf-ink-dim">Nothing here.</p>
      ) : (
        <div className="space-y-2">
          {items.map(t => (
            <div key={t.id}
                 className="flex items-start gap-3 rounded-xl border border-sf-line bg-sf-card px-3 py-2.5">
              <button type="button" onClick={() => setEditTodo(t)} className="min-w-0 flex-1 text-left">
                {/* The title wraps in full; the notes stay a one-line preview,
                    which is what the age chip beside it is scanned against. */}
                <p className="text-sm break-words text-sf-ink">{t.title}</p>
                {t.notes && <p className="truncate text-xs text-sf-ink-dim">{t.notes}</p>}
              </button>
              {t.context && (
                <span className="shrink-0 rounded-full bg-sf-bg px-2 py-0.5 text-xs text-sf-ink-dim">
                  {t.context}
                </span>
              )}
              <span className="shrink-0 rounded-full bg-sf-bg px-2 py-0.5 text-xs text-sf-ink-dim"
                    title="Time since last touched">
                {formatAge(t.updated_at)}
              </span>
              <button
                type="button"
                onClick={() => void setStatus(t, 'next_action')}
                className="shrink-0 rounded-lg border border-sf-line-strong px-2.5 py-1.5 text-xs font-display text-sf-ink hover:bg-sf-hover"
                title="Reactivate as a next action"
              >
                → Next
              </button>
            </div>
          ))}
        </div>
      )}
    </section>
  );

  return (
    <TodoShell active="waiting" onAdded={reload} scoped>
      <SearchFilterBar
        query={search}
        onQueryChange={setSearch}
        placeholder="Filter…"
        visibleCount={memoWaiting.length + memoDelegated.length}
        totalCount={(waiting?.length ?? 0) + (delegated?.length ?? 0)}
        countNoun="item"
        active={search.trim() !== ''}
        activeFacetCount={0}
        onClear={() => setSearch('')}
      />
      {failed && <LoadFailed retry={reload} />}
      {!failed && loading && <LoadingRows />}
      {!failed && !loading && memoWaiting.length + memoDelegated.length === 0 && !search && (
        <EmptyState title="Nothing waiting" hint="Items blocked on someone else land here from triage." />
      )}
      {!failed && !loading && (
        <div className="space-y-6">
          {section('Waiting for', memoWaiting)}
          {section('Delegated', memoDelegated)}
        </div>
      )}
      {editTodo && (
        <TodoEditSheet
          todo={editTodo}
          projects={projects}
          contexts={filters?.contexts ?? []}
          onClose={() => setEditTodo(null)}
          onSaved={after}
        />
      )}
    </TodoShell>
  );
}

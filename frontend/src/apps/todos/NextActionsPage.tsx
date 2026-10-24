import { useMemo, useState } from 'react';
import { SearchFilterBar, toggleValue } from './lib/search';
import { TodoEditSheet } from './components/TodoEditSheet';
import { TodoRow } from './components/TodoRow';
import { contextGroup, matchesContexts, matchesPeople, peopleGroup } from './contextFacet';
import { useRowActions, useStatusList } from './hooks';
import { useScope } from './scope';
import { EmptyState, LoadFailed, LoadingRows, TodoShell } from './TodoShell';
import type { Todo } from './types';
import { useTodoMeta } from './useTodoMeta';
import { matchesFilter } from './util';

const NO_CONTEXT = 'No context';

/** Next actions: the starred handful pinned on top, then grouped by context
 * for batching (@calls together, @errands together).
 *
 * The context grouping IS the page's purpose — flattening the groups into a sort order would
 * quietly remove the batching this page exists for. Filtering is the shared
 * `SearchFilterBar`, page-owns-state. */
export function NextActionsPage() {
  const { todos, failed, reload } = useStatusList('next_action', useScope());
  const { toggleDone, toggleStar, after } = useRowActions(reload);
  const { projects, filters } = useTodoMeta();
  const [search, setSearch] = useState('');
  const [contexts, setContexts] = useState<(string | number)[]>([]);
  const [people, setPeople] = useState<(string | number)[]>([]);
  const [editTodo, setEditTodo] = useState<Todo | null>(null);
  const [adding, setAdding] = useState(false);

  const visible = useMemo(
    () => (todos ?? []).filter(
      t => matchesContexts(t.context, contexts) && matchesPeople(t.people, people)
        && matchesFilter(t, search),
    ),
    [todos, search, contexts, people],
  );

  const starred = visible.filter(t => t.star);
  const groups = useMemo(() => {
    const byContext = new Map<string, Todo[]>();
    for (const t of visible.filter(v => !v.star)) {
      const key = t.context || NO_CONTEXT;
      byContext.set(key, [...(byContext.get(key) ?? []), t]);
    }
    return [...byContext.entries()].sort(([a], [b]) => {
      if (a === NO_CONTEXT) return 1;
      if (b === NO_CONTEXT) return -1;
      return a.localeCompare(b);
    });
  }, [visible]);

  const rows = (items: Todo[]) => (
    <div className="space-y-2">
      {items.map(t => (
        <TodoRow key={t.id} todo={t} onToggleDone={toggleDone}
                 onToggleStar={toggleStar} onEdit={setEditTodo} />
      ))}
    </div>
  );

  return (
    <TodoShell active="next" onAdded={reload} scoped>
      <div className="mb-3 flex items-center justify-between gap-2">
        <p className="text-sm text-sf-ink-dim">{visible.length} next action{visible.length === 1 ? '' : 's'}</p>
        <button
          type="button"
          onClick={() => setAdding(true)}
          className="rounded-lg bg-sf-accent px-3 py-1.5 text-sm font-display text-sf-accent-ink hover:bg-sf-accent-dark"
        >
          Add next action
        </button>
      </div>
      <SearchFilterBar
        query={search}
        onQueryChange={setSearch}
        placeholder="Filter…"
        groups={[
          contextGroup(
            filters?.contexts ?? [],
            contexts,
            v => setContexts(prev => toggleValue(prev, v)),
          ),
          peopleGroup(
            filters?.people ?? [],
            people,
            v => setPeople(prev => toggleValue(prev, v)),
          ),
        ]}
        visibleCount={visible.length}
        totalCount={todos?.length ?? 0}
        countNoun="next action"
        active={search.trim() !== '' || contexts.length + people.length > 0}
        activeFacetCount={contexts.length + people.length}
        onClear={() => { setSearch(''); setContexts([]); setPeople([]); }}
      />
      {failed && <LoadFailed retry={reload} />}
      {!failed && todos === null && <LoadingRows />}
      {todos !== null && !failed && visible.length === 0 && (
        <EmptyState title="No next actions" hint="Triage your inbox, or add one above." />
      )}
      <div className="space-y-6">
        {starred.length > 0 && (
          <section>
            <h2 className="mb-2 text-xs font-display font-bold uppercase tracking-wide text-sf-amber-text">
              ★ Starred
            </h2>
            {rows(starred)}
          </section>
        )}
        {groups.map(([context, items]) => (
          <section key={context}>
            <h2 className="mb-2 text-xs font-display font-bold uppercase tracking-wide text-sf-ink-dim">
              {context}
            </h2>
            {rows(items)}
          </section>
        ))}
      </div>
      {(editTodo || adding) && (
        <TodoEditSheet
          todo={editTodo}
          defaults={{ status: 'next_action' }}
          projects={projects}
          contexts={filters?.contexts ?? []}
          onClose={() => { setEditTodo(null); setAdding(false); }}
          onSaved={after}
        />
      )}
    </TodoShell>
  );
}

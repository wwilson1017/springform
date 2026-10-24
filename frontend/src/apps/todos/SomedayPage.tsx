import { useMemo, useState } from 'react';
import { SearchFilterBar, toggleValue } from './lib/search';
import { TodoEditSheet } from './components/TodoEditSheet';
import { TodoRow } from './components/TodoRow';
import { contextGroup, matchesContexts } from './contextFacet';
import { useRowActions, useStatusList } from './hooks';
import { useScope } from './scope';
import { EmptyState, FilterEmptyState, LoadFailed, LoadingRows, TodoShell } from './TodoShell';
import type { Todo } from './types';
import { useTodoMeta } from './useTodoMeta';
import { matchesFilter, todayStr } from './util';

/** Someday/maybe: a flat list with a search box and a context filter. Items whose
 * bring-back date has arrived sit on top; they stay someday until you decide
 * otherwise, and "→ Next" on a row is that decision. */
export function SomedayPage() {
  const { todos, failed, reload } = useStatusList('someday_maybe', useScope());
  const { toggleDone, toggleStar, setStatus, after } = useRowActions(reload);
  const { projects, filters } = useTodoMeta();
  const [search, setSearch] = useState('');
  const [contexts, setContexts] = useState<(string | number)[]>([]);
  const [editTodo, setEditTodo] = useState<Todo | null>(null);

  const visible = useMemo(
    () => (todos ?? []).filter(
      t => matchesContexts(t.context, contexts) && matchesFilter(t, search)),
    [todos, search, contexts]);
  const today = todayStr(new Date(), filters?.tz);
  const isBack = (t: Todo) => !!t.revisit_on && t.revisit_on <= today;
  const back = visible.filter(isBack);

  const rows = (items: Todo[]) => (
    <div className="space-y-2">
      {items.map(t => (
        <div key={t.id} className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <TodoRow todo={t} onToggleDone={toggleDone}
                     onToggleStar={toggleStar} onEdit={setEditTodo} />
          </div>
          <button
            type="button"
            onClick={() => void setStatus(t, 'next_action')}
            className="mt-1 shrink-0 rounded-lg border border-sf-line-strong px-2.5 py-1.5 text-xs font-display text-sf-ink hover:bg-sf-hover"
            title="Commit to this — move it to next actions"
          >
            → Next
          </button>
        </div>
      ))}
    </div>
  );

  return (
    <TodoShell active="someday" onAdded={reload} scoped>
      <SearchFilterBar
        query={search}
        onQueryChange={setSearch}
        placeholder="Filter…"
        groups={[contextGroup(
          filters?.contexts ?? [],
          contexts,
          v => setContexts(prev => toggleValue(prev, v)),
        )]}
        visibleCount={visible.length}
        totalCount={todos?.length ?? 0}
        countNoun="item"
        active={search.trim() !== '' || contexts.length > 0}
        activeFacetCount={contexts.length}
        onClear={() => { setSearch(''); setContexts([]); }}
      />
      {failed && <LoadFailed retry={reload} />}
      {!failed && todos === null && <LoadingRows />}
      {!failed && todos !== null && todos.length === 0 && (
        <EmptyState title="Nothing in someday/maybe" hint="Ideas you might do later land here from triage." />
      )}
      {!failed && todos !== null && todos.length > 0 && visible.length === 0 && <FilterEmptyState />}
      {back.length > 0 && (
        <section className="mb-6">
          <h2 className="mb-2 text-xs font-display font-bold uppercase tracking-wide text-sf-ink-dim">
            Time to revisit
          </h2>
          {rows(back)}
        </section>
      )}
      {rows(visible.filter(t => !isBack(t)))}
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

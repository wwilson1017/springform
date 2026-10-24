import { useMemo, useState } from 'react';
import { SearchFilterBar, toggleValue } from './lib/search';
import { TodoEditSheet } from './components/TodoEditSheet';
import { TodoRow } from './components/TodoRow';
import { contextGroup, matchesContexts, matchesPeople, peopleGroup } from './contextFacet';
import { useRowActions, useStatusList } from './hooks';
import { useScope } from './scope';
import { EmptyState, FilterEmptyState, LoadFailed, LoadingRows, TodoShell } from './TodoShell';
import type { Todo } from './types';
import { useTodoMeta } from './useTodoMeta';
import { matchesFilter } from './util';

/** Finished items, newest-finished first (server-ordered — the page never re-sorts).
 *  The Dropped tab is the archive: nothing is ever deleted, and an item dropped by
 *  mistake is brought back from here by editing its status. */
export function DonePage() {
  const [mode, setMode] = useState<'done' | 'dropped'>('done');
  // `mode` rides in the refetch key — switching tabs re-runs the fetch.
  const { todos, failed, reload } = useStatusList(mode, useScope(), 200);
  const { toggleDone, toggleStar, after } = useRowActions(reload);
  const { projects, filters } = useTodoMeta();
  const [search, setSearch] = useState('');
  const [contexts, setContexts] = useState<(string | number)[]>([]);
  const [people, setPeople] = useState<(string | number)[]>([]);
  const [editTodo, setEditTodo] = useState<Todo | null>(null);

  const visible = useMemo(
    () => (todos ?? []).filter(
      t => matchesContexts(t.context, contexts) && matchesPeople(t.people, people)
        && matchesFilter(t, search),
    ),
    [todos, search, contexts, people],
  );

  return (
    <TodoShell active="done" onAdded={reload} scoped>
      <div className="mb-4 flex gap-1 border-b border-sf-line">
        {(['done', 'dropped'] as const).map(m => (
          <button
            key={m}
            type="button"
            onClick={() => setMode(m)}
            aria-pressed={mode === m}
            className={`px-4 py-2 text-sm capitalize transition-colors border-b-2 -mb-px ${
              mode === m
                ? 'text-sf-ink font-semibold border-sf-accent'
                : 'text-sf-ink-dim font-medium border-transparent hover:text-sf-ink'
            }`}
          >
            {m}
          </button>
        ))}
      </div>
      <SearchFilterBar
        query={search}
        onQueryChange={setSearch}
        placeholder="Search finished todos…"
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
        countNoun="todo"
        active={search.trim() !== '' || contexts.length + people.length > 0}
        activeFacetCount={contexts.length + people.length}
        onClear={() => { setSearch(''); setContexts([]); setPeople([]); }}
      />
      {failed && <LoadFailed retry={reload} />}
      {!failed && todos === null && <LoadingRows />}
      {!failed && todos !== null && todos.length === 0 && (
        <EmptyState title={mode === 'dropped' ? 'Nothing dropped' : 'Nothing finished yet'} />
      )}
      {!failed && todos !== null && todos.length > 0 && visible.length === 0 && <FilterEmptyState />}
      <div className="space-y-2">
        {visible.map(t => (
          <TodoRow key={t.id} todo={t} onToggleDone={toggleDone}
                   onToggleStar={toggleStar} onEdit={setEditTodo} />
        ))}
      </div>
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

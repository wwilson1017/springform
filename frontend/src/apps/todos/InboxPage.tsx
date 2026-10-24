import { useState } from 'react';
import { SearchFilterBar, toggleValue } from './lib/search';
import { QuickAdd } from './components/QuickAdd';
import { TodoEditSheet } from './components/TodoEditSheet';
import { TriageCard } from './components/TriageCard';
import { UndoPill } from './components/UndoPill';
import { contextGroup, matchesContexts, matchesPeople, peopleGroup } from './contextFacet';
import { useInboxFocus, useStatusList } from './hooks';
import { useScope } from './scope';
import { EmptyState, FilterEmptyState, LoadFailed, LoadingRows, TodoShell } from './TodoShell';
import type { Todo } from './types';
import { refreshMeta, useTodoMeta } from './useTodoMeta';
import { matchesFilter } from './util';

/** GTD triage — one item at a time. The head item gets the big card; the
 * rest wait in a compact list and can be promoted by clicking.
 *
 * A triage instrument, not a records list: one item is promoted to a full card and the
 * remainder is a promote-only queue. Filtering is the shared `SearchFilterBar`, page-owns-state. */
export function InboxPage() {
  const { todos, failed, reload } = useStatusList('inbox', useScope());
  const { projects, filters } = useTodoMeta();
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [editTodo, setEditTodo] = useState<Todo | null>(null);
  const [search, setSearch] = useState('');
  const [contexts, setContexts] = useState<(string | number)[]>([]);
  const [people, setPeople] = useState<(string | number)[]>([]);
  // Bumped only by an undo (below), and part of the card's key — so the restored
  // item always gets a FRESH card. A resolving write leaves `TriageCard` busy on
  // purpose, spent, counting on the reload to swap in a different head item and
  // remount it; but `useTodos` cancels a superseded fetch, so an undo clicked
  // before the filing refetch lands cancels that refetch, the list never drops
  // the item, and the same permanently-disabled card would still be mounted
  // under the same id.
  const [focusSeq, setFocusSeq] = useState(0);

  // todo-gtd #2925 — an undone filing puts the item back in the inbox, and the decision
  // behind that issue is that it must come back as the CURRENT triage card
  // rather than be corrected silently somewhere down the queue. Without this the
  // item returns to the list but the card shows whatever `items[0]` happens to
  // be, so the user has no way to see the correction take effect.
  //
  // The filter bar is CLEARED with it, and that is the implementation of "show me
  // this item" rather than a side effect of it. Selecting the row is not enough on
  // its own: `items` is filtered before `head` is picked, so a restored item the
  // bar excludes falls straight through to `items[0]` and the undo looks like it
  // did nothing — the exact failure this focus exists to prevent.
  //
  // It is reachable. `matchesContexts` and `matchesFilter` read only `context`, so
  // while the triage picker was the one way to file, undo restored the very field
  // the filter reads and visibility came back by itself. `TodoEditSheet` files too
  // (see its `save`), and THAT write also carries the title, notes and project —
  // rename an item while filing it under a search and undo puts it back in the
  // inbox wearing a title the search no longer matches. The user's last action was
  // Undo on a row they picked by name, so showing that row is what they asked for;
  // the query is one keystroke to retype and the item is on screen either way.
  useInboxFocus(id => {
    setSelectedId(id);
    setSearch('');
    setContexts([]);
    setPeople([]);
    setFocusSeq(n => n + 1);
  });

  const items = (todos ?? []).filter(
    t => matchesContexts(t.context, contexts) && matchesPeople(t.people, people)
      && matchesFilter(t, search),
  );
  const head = items.find(t => t.id === selectedId) ?? items[0];
  const rest = items.filter(t => head && t.id !== head.id);

  // Two callbacks, because they mean different things to the selection. An
  // in-place edit (title, project, star) must NOT move you to another card —
  // clearing the selection there bounced a manually-picked item back to the
  // head of the list mid-triage.
  const changed = () => {
    reload();
    void refreshMeta();
  };

  const processed = () => {
    setSelectedId(null);
    changed();
  };

  return (
    <TodoShell active="inbox" hideQuickAdd inlineUndo={!editTodo} scoped>
      <SearchFilterBar
        query={search}
        onQueryChange={setSearch}
        // Preserved verbatim — `InboxPage.test.tsx` selects the input by this placeholder.
        placeholder="Search inbox…"
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
        visibleCount={items.length}
        totalCount={todos?.length ?? 0}
        countNoun="capture"
        active={search.trim() !== '' || contexts.length + people.length > 0}
        activeFacetCount={contexts.length + people.length}
        onClear={() => { setSearch(''); setContexts([]); setPeople([]); }}
      />
      {/* Capture lives in the page body on the Inbox, right above the card you
          are triaging, instead of up in the shell above the filters. It is a
          full-width body row on every viewport, so the order against the filter bar reads
          the same on a phone. Hence one instance, no breakpoint branch, and no
          `width` prop: it already fills its container. */}
      <div className="mb-4">
        <QuickAdd onAdded={changed} />
      </div>
      {failed && <LoadFailed retry={reload} />}
      {!failed && todos === null && <LoadingRows />}
      {todos !== null && !failed && items.length === 0 && (
        (todos?.length ?? 0) > 0
          ? <FilterEmptyState />
          : <EmptyState title="Inbox zero" hint="Everything is captured and clarified. Mind like water." />
      )}
      {head && (
          /* Keyed by id: the card holds the chosen destination in local state
              until it is filed, and that choice belongs to ONE item. The undo
              counter rides along so a restored item never reuses the spent card
              it was filed from (see `focusSeq`). */
          <TriageCard
            key={`${head.id}:${focusSeq}`}
            todo={head}
            projects={projects}
            contexts={filters?.contexts ?? []}
            onProcessed={processed}
            onChanged={changed}
            onEdit={setEditTodo}
          />
      )}
      {/* The undo notice, in the flow: right under the card (or the empty state, once
          the last item is filed) and above the queue — where the eyes already are.
          Except while the edit sheet is open: its `z-50` overlay would cover an inline
          row whose 7s window keeps running, so the notice moves to the shell's floating
          copy, which sits above the sheet, and returns here when the sheet closes. */}
      {!editTodo && <UndoPill inline />}
      {head && rest.length > 0 && (
            <div className="mt-4">
              <h2 className="mb-2 text-xs font-display font-bold uppercase tracking-wide text-sf-ink-dim">
                {rest.length} more in inbox
              </h2>
              {/* Promote-only, deliberately. The whole row is one "triage this
                  one next" target, so its title must never become a click-to-
                  rename editor the way the card's is — an edit box opening
                  mid-row makes skipping between items fiddly, and the item is
                  about to land on the card where renaming belongs. If TodoRow
                  ever gains inline rename, this list stays plain.
                  Pinned by InboxPage.test.tsx. */}
              {/* `data-inbox-queue` is the test's handle on these rows. It used
                  to select them by their `truncate` class, which tied a test to
                  a styling decision — and broke the moment the titles were made
                  to wrap. Select on this, never on a utility class. */}
              <div className="space-y-1" data-inbox-queue>
                {rest.map(t => (
                  <button
                    key={t.id}
                    type="button"
                    onClick={() => setSelectedId(t.id)}
                    // Wraps: choosing which capture to triage next is exactly
                    // the moment you need to read the whole thing.
                    className="block w-full break-words rounded-lg border border-sf-line bg-sf-card px-3 py-2 text-left text-sm text-sf-ink hover:border-sf-accent/40"
                  >
                    {t.title}
                  </button>
                ))}
              </div>
            </div>
      )}
      {editTodo && (
        <TodoEditSheet
          todo={editTodo}
          projects={projects}
          contexts={filters?.contexts ?? []}
          onClose={() => setEditTodo(null)}
          onSaved={changed}
        />
      )}
    </TodoShell>
  );
}

import { useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router';
import { QuickAdd } from './components/QuickAdd';
import { BottomBar, TopMenu } from './components/ShellMenu';
import { UndoPill } from './components/UndoPill';
import { useMediaQuery } from './lib/useMediaQuery';
import { PHONE_QUERY, todoPath, type ListKey } from './menu';
import { setScope, useScope } from './scope';
import { useToasts } from './toast';
import { useTodoMeta } from './useTodoMeta';

/** A page's identity for the shell: one of the menu's lists, or a page reached from one
 *  (a todo's own page). The lists themselves are defined in ./menu. */
export type TodoTab = ListKey | 'item';

interface Props {
  active: TodoTab;
  /** Hide QuickAdd on pages that would fight it with their own form (Review)
   * or that render their own copy lower down the page (Inbox). */
  hideQuickAdd?: boolean;
  onAdded?: () => void;
  /** The page renders <UndoPill inline /> itself (Inbox), so the floating one is left out. */
  inlineUndo?: boolean;
  /** The page honours Mine / Everyone (scope.ts), so the shell shows the switch. */
  scoped?: boolean;
  children: React.ReactNode;
}

/** The bottom bar's height; the page and the floating stack keep clear of it. */
const BAR = 'calc(3.5rem + env(safe-area-inset-bottom, 0px))';

/** Shared shell for every Todos page, inside the core Layout. The app uses flat sibling routes,
 * so this mounts fresh per page; meta comes from the module-level stale-while-revalidate cache
 * in useTodoMeta, which is what keeps the inbox badge from flashing on tab switches. */
export function TodoShell({ active, hideQuickAdd, onAdded, inlineUndo, scoped, children }: Props) {
  const { filters, refreshMeta } = useTodoMeta();
  const [query, setQuery] = useState('');
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const toasts = useToasts();
  const scope = useScope();
  const inboxCount = filters?.status_counts.inbox ?? 0;
  useEffect(() => { document.title = 'Todos'; }, []);
  const phone = useMediaQuery(PHONE_QUERY);

  // Keep the header box in sync with ?q= while ON the results page — covers
  // deep links and Back/Forward; elsewhere the box stays a blank launcher.
  // Adjust-during-render (not an effect): re-sync only when the URL value
  // changes, so typing in the box is never clobbered.
  const onSearchPage = active === 'search';
  const urlQuery = onSearchPage ? (searchParams.get('q') ?? '') : '';
  // Starts '' (the box's own initial value), not urlQuery: the shell mounts fresh per
  // page, so a deep link's ?q= has to count as a change on the first render too.
  const [prevUrlQuery, setPrevUrlQuery] = useState('');
  if (prevUrlQuery !== urlQuery) {
    setPrevUrlQuery(urlQuery);
    setQuery(urlQuery);
  }

  const menu = { active, inboxCount };

  return (
    <div style={{ '--bottom-bar': phone ? BAR : '0px' } as React.CSSProperties}>
      <div className="mx-auto max-w-5xl px-4 pb-[calc(var(--bottom-bar)+2.5rem)] pt-4 md:px-8">
        <div className="flex items-center gap-3">
          <h1 className="m-0 min-w-0 truncate font-display text-xl font-medium text-sf-ink">
            <Link to={todoPath('')} className="text-sf-ink no-underline">Todos</Link>
          </h1>
          <div className="ml-auto flex items-center gap-2">
            {scoped && (
              <div role="group" aria-label="Whose todos" className="flex rounded-lg border border-sf-line-strong bg-sf-card p-0.5 text-sm">
                {(['mine', 'all'] as const).map(s => (
                  <button key={s} type="button" aria-pressed={scope === s} onClick={() => setScope(s)}
                    title={s === 'mine' ? 'Your private todos, team todos assigned to you, and unassigned team todos' : 'Every todo you can see'}
                    className={`cursor-pointer rounded-md border-0 px-2.5 py-1 ${scope === s ? 'bg-sf-raised font-semibold text-sf-ink' : 'bg-transparent text-sf-ink-dim hover:text-sf-ink'}`}>
                    {s === 'mine' ? 'Mine' : 'Everyone'}
                  </button>
                ))}
              </div>
            )}
            <form
              role="search"
              onSubmit={e => {
                e.preventDefault();
                navigate(todoPath(`/search?q=${encodeURIComponent(query.trim())}`));
              }}
            >
              <input
                value={query}
                onChange={e => setQuery(e.target.value)}
                placeholder="Search…"
                aria-label="Search all todos"
                className="h-9 w-28 sm:w-44 rounded-lg border border-sf-line-strong bg-sf-card px-3 text-base sm:text-sm text-sf-ink placeholder:text-sf-ink-dim focus:border-sf-accent focus:outline-none"
              />
            </form>
          </div>
        </div>

        {!phone && <TopMenu {...menu} />}

        {!hideQuickAdd && (
          <div className="mt-4">
            <QuickAdd onAdded={() => { void refreshMeta(); onAdded?.(); }} />
          </div>
        )}

        <div className="mt-5">{children}</div>
      </div>

      {phone && <BottomBar {...menu} />}

      {/* ONE bottom stack for both transient surfaces: undoing a repeating todo fires the
          reopened-successor toast while the undo pill is showing, and two independently
          positioned fixed containers would overlap on a phone. `pointer-events-none` on the
          full-width wrapper is mandatory, or an invisible bar swallows clicks across the
          viewport; each child opts back in. On a phone the stack sits above the bottom bar. */}
      <div className="pointer-events-none fixed inset-x-0 bottom-[calc(var(--bottom-bar)+1rem)] z-50 flex flex-col items-center gap-2 px-4">
        {toasts.map(t => (
          <div
            key={t.id}
            role="status"
            className={`pointer-events-auto w-full max-w-sm rounded-xl border px-4 py-2.5 text-sm shadow-lg text-sf-ink ${
              t.kind === 'error' ? 'border-sf-red/40 bg-sf-card' : 'border-sf-line-strong bg-sf-card'
            }`}
          >
            {t.text}
          </div>
        ))}
        {!inlineUndo && <UndoPill />}
      </div>
    </div>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="rounded-xl border border-sf-line bg-sf-card p-8 text-center">
      <p className="font-display font-semibold text-sf-ink">{title}</p>
      {hint && <p className="mt-1 text-sm text-sf-ink-dim">{hint}</p>}
    </div>
  );
}

/** Shown when a client-side filter hides every row of a non-empty list — distinct from the true
 *  empty states above, which mean the LIST is empty. */
export function FilterEmptyState() {
  return (
    <div className="rounded-xl border border-sf-line bg-sf-card p-8 text-center">
      <p className="text-sm text-sf-ink-dim">No todos match your filter.</p>
    </div>
  );
}

export function LoadingRows() {
  return <p className="py-6 text-center text-sm text-sf-ink-dim">Loading…</p>;
}

export function LoadFailed({ retry }: { retry: () => void }) {
  return (
    <div className="rounded-xl border border-sf-red/40 bg-sf-red/10   p-4 text-sm text-sf-ink">
      Couldn't load todos.{' '}
      <button type="button" onClick={retry} className="underline">Retry</button>
    </div>
  );
}

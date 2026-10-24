import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { apiErrorMessage } from '../errors';
import { createProject, updateTodo } from '../api';
import { dropUndo, queueUndo } from '../undoQueue';
import { toast } from '../toast';
import type { Todo, TodoProject, TodoStatus } from '../types';
import { useListFilters } from '../useTodoMeta';
import { parseTags } from '../util';
import { PeopleInput } from './PeopleInput';
import { EMPTY_PROJECT_FIELDS } from '../constants';
import { ProjectDetails, ProjectFields } from './ProjectFields';
import { SourceLabel } from './SourceLabel';
import { InlineTitle } from '../lib/inline-edit';
import { useAutoSave } from '../lib/autosave';

interface Props {
  todo: Todo;
  projects: TodoProject[];
  /** Contexts already in use — the options for the final "set context" step. */
  contexts: string[];
  /** After a write that takes the item OUT of the inbox (filed/done/deleted). */
  onProcessed: () => void;
  /** After an in-place change that leaves it in the inbox (title, project, …). */
  onChanged: () => void;
  onEdit: (todo: Todo) => void;
}

// Where the item lands once it is filed. Picking one is a LOCAL decision —
// nothing is written until the context step, so the item stays in the inbox
// (and on this card) while you keep clarifying it.
const DESTINATIONS: { label: string; status: TodoStatus; list: string }[] = [
  { label: 'Next action', status: 'next_action', list: 'To Do' },
  { label: 'Waiting', status: 'waiting_for', list: 'Waiting For' },
  { label: 'Delegated', status: 'delegated', list: 'Delegated' },
  { label: 'Someday', status: 'someday_maybe', list: 'Someday / Maybe' },
];

// The picker's option values are INDICES, never the context strings: a context
// a user really named "new" would otherwise collide with the sentinel and be
// impossible to select.
const NEW_CONTEXT = 'new';

// The project picker's option values are numeric ids, so a non-numeric sentinel
// cannot collide with a real one however the project is named.
const NEW_PROJECT = 'new';

// The step heading's own type — todo-gtd #2508 settled its size and contrast. The bottom margin moved
// to `StepBar` below, which is now what the headings are wrapped in.
const stepCls = 'text-sm font-display font-bold uppercase tracking-wide text-sf-ink';
const destCls =
  'rounded-lg border px-3 py-2 text-sm font-display transition-colors disabled:opacity-50';
const inputCls =
  'rounded-lg border border-sf-line-strong bg-sf-card px-2 py-1.5 text-sm text-sf-ink focus:border-sf-accent focus:outline-none disabled:opacity-50';
const linkCls = 'text-sm underline disabled:opacity-50';
// The visible name over each step-2 field, so nothing there is a guess.
const fieldCls = 'mb-1 block text-xs font-semibold text-sf-ink';

/** One clarify step's heading bar (issue todo-gtd #2613): a solid red number chip in a shaded row,
 * then the heading text — and, on step 3 only, the red star that REPLACED the word
 * "(required)" the heading used to spell out.
 *
 * Declared at module level on purpose. A component declared inside another is a new function
 * identity on every render, so React remounts the whole subtree — and this card holds live
 * draft state (notes, an inline rename) that a remount would throw away.
 *
 * The chip and the star are both `aria-hidden`, because neither reads as anything useful out
 * loud ("zero one", "black star"), and the `sr-only` spans say the same thing in words. So the
 * accessible name of step 3's heading is still "Step 3: Last step — set context (required)" —
 * exactly what the visible text said before the number and the word moved into glyphs.
 */
function StepBar({ n, required = false, children }: {
  n: number;
  required?: boolean;
  children: ReactNode;
}) {
  return (
    <div className="mb-2 flex items-center gap-2 rounded-lg bg-sf-bg px-2.5 py-1.5">
      <span
        aria-hidden="true"
        className="rounded bg-sf-accent px-1.5 py-0.5 font-display text-xs font-bold leading-none tabular-nums text-sf-accent-ink"
      >
        {String(n).padStart(2, '0')}
      </span>
      <h3 className={stepCls}>
        <span className="sr-only">Step {n}: </span>
        {children}
        {required && (
          <span className="ml-1 text-sf-accent-text" aria-hidden="true">★</span>
        )}
        {required && <span className="sr-only"> (required)</span>}
      </h3>
    </div>
  );
}

/** GTD triage — one inbox item at a time, as three deliberate clarify steps:
 * what kind of action it is, optional detail, then the context that files it.
 * Setting a context is the ONLY way out of the inbox (issue todo-gtd #1548). */
export function TriageCard({ todo, projects, contexts, onProcessed, onChanged, onEdit }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [destination, setDestination] = useState<TodoStatus>('next_action');
  // A rename this card just made, until the parent's reload feeds it back in
  // through `todo`. Blur-then-click means clicking Edit STARTS the rename and
  // opens the sheet in the same gesture, and the sheet snapshots the title it
  // is handed and writes it back on its next full-field save — so handing it
  // the stale prop silently reverts the rename the user just made.
  const [pendingTitle, setPendingTitle] = useState<string | null>(null);
  // null = the context picker is showing; a string = the inline create input is.
  const [newContext, setNewContext] = useState<string | null>(null);
  // Same shape for the project picker in step 2.
  const [newProject, setNewProject] = useState<string | null>(null);
  // The new project's area / purpose / outcome, sent with its name on Create.
  const [newProjectFields, setNewProjectFields] = useState(EMPTY_PROJECT_FIELDS);
  // A native date input ignores `placeholder`, so step 2's empty-state cue is an
  // overlay that has to know when the field has focus (issue todo-gtd #2351).
  const [dueFocused, setDueFocused] = useState(false);
  // Opening the sheet waits on the notes flush, which is a round trip on a slow link.
  const [editPending, setEditPending] = useState(false);
  // The date in the box that the row does not hold yet: still being typed, or sent and not
  // yet answered. The input is CONTROLLED, so without it a typed date would never show, and
  // a saved one would blank (with the "Add due date" cue flashing back over it) for the
  // whole length of the refetch. null = the box shows the row's own date.
  const [pendingDue, setPendingDue] = useState<string | null>(null);
  // The same value, live: the due-date save outlives the render that started it.
  const dueLive = useRef<string | null>(null);
  const setDue = (value: string | null) => { dueLive.current = value; setPendingDue(value); };
  // People, typed the way tags are. Re-seeded during render whenever the row's own
  // list changes (this card's save echoing back, or an edit made in the sheet).
  const savedPeople = (todo.people ?? []).join(', ');
  const [peopleDraft, setPeopleDraft] = useState(savedPeople);
  const [seededPeople, setSeededPeople] = useState(savedPeople);
  if (seededPeople !== savedPeople) {
    setSeededPeople(savedPeople);
    setPeopleDraft(savedPeople);
  }
  // Tags, the same way.
  const savedTags = todo.tags.join(', ');
  const [tagsDraft, setTagsDraft] = useState(savedTags);
  const [seededTags, setSeededTags] = useState(savedTags);
  if (seededTags !== savedTags) {
    setSeededTags(savedTags);
    setTagsDraft(savedTags);
  }
  const listFilters = useListFilters();
  const knownPeople = listFilters?.people ?? [];
  const knownTags = listFilters?.tags ?? [];
  const areas = listFilters?.areas ?? [];
  // The project this item is filed under — its fields open up below the picker.
  const project = projects.find(p => p.id === todo.project_id);
  // THE ROW, as this card best knows it — not the `todo` prop.
  //
  // The prop lags: the parent refetches asynchronously, so between a write being sent and
  // that refetch landing the prop still describes the row as it was. Rendering from the prop
  // is what made the date field blank and the notes box rewind. So the card keeps its own
  // view of the row and advances it from whichever source is NEWER — a `todo` prop, or the
  // row a write of ours answered with. `at` is the version that ordering is done on;
  // `rev` (the row's change-feed version) grows with every write, and text alone cannot tell
  // an outside edit from this card's own write echoing back off a stale read.
  //
  // Crucially the whole ROW is adopted, never just its version: a write of ours answers with
  // the row as the server has it, INCLUDING fields someone else changed in the meantime.
  // Recording that version without taking its content is a silent clobber — the later refetch
  // carries the same version, so it is rejected as an echo, the box goes on showing the text
  // from before the outside edit, and the next blur writes it back over them.
  const [row, setRow] = useState(() => ({
    at: todo.rev,
    notes: todo.notes ?? '',
    due: todo.due_date ?? '',
    title: todo.title,
  }));
  // What the notes box shows. Dirty is `notesDraft !== row.notes`, so the baseline moves the
  // moment a write is acknowledged rather than when the refetch lands — otherwise the field
  // reads dirty, and re-sends, for a whole round trip after it was already saved.
  const [notesDraft, setNotesDraft] = useState(todo.notes ?? '');
  // The notes value already handed to the server — and the request itself. The first lets the
  // unmount flush below tell "still in flight" from "queued and about to be dropped"; the
  // second lets it queue BEHIND that request instead of racing it.
  const sentNotes = useRef<string | null>(null);
  const notesInFlight = useRef<Promise<unknown> | null>(null);
  // Set once the row is gone: a parting write to a deleted todo is a pointless 404.
  const goneRef = useRef(false);
  const dest = DESTINATIONS.find(d => d.status === destination) ?? DESTINATIONS[0];

  // An inbox item can already carry a context (Quick Add parses "@ctx" while
  // keeping status: inbox), and the shared meta can still be empty while it
  // loads — offer the item's own context either way so the card always has a
  // way out that isn't "retype what is already there".
  const options = useMemo(() => {
    const known = contexts.filter(Boolean);
    return todo.context && !known.includes(todo.context) ? [todo.context, ...known] : known;
  }, [contexts, todo.context]);

  /** Take a newer view of the row — from the parent's prop or from a write's own response —
   * and move every optimistic value onto it. Older or equal rows are ignored: they are this
   * card's own write echoing back off a read taken before it committed.
   *
   * Two rules keep it from destroying work. Unsaved text of the user's own is never
   * overwritten; it stays on screen and stays dirty — the notes, and a date still being typed
   * (`pendingDue` is released by its own save, never here). And the title override is cleared
   * only when the row DISAGREES with it — clearing one that already matches would just churn
   * state, and the value it holds is the one the user is looking at. */
  const adopt = (r: Pick<Todo, 'rev' | 'notes' | 'due_date' | 'title'>) => {
    const at = r.rev;
    if (at <= row.at) return;
    const notes = r.notes ?? '';
    const due = r.due_date ?? '';
    setRow({ at, notes, due, title: r.title });
    if (notesDraft === row.notes) setNotesDraft(notes);
    if (pendingTitle !== null && pendingTitle !== r.title) setPendingTitle(null);
  };

  // The parent's refetch, adopted during render — deliberately not in an effect, which would
  // paint the stale value first. React's documented adjust-state-during-render; it converges
  // in one pass because `row.at` then equals the prop's.
  adopt(todo);
  // The latest render's `adopt`, which is what every write's ANSWER goes through. An answer
  // can outlive the render that sent it: the due-date save leaves the card editable and lets
  // other writes run alongside, so by the time one answers, its own closure knows neither
  // what has been typed in the notes box since (it would read the box as untouched and put
  // the server's old notes back over it) nor which rows have arrived since (it would take an
  // older row for a newer one and rewind the date).
  const adoptRef = useRef(adopt);
  useLayoutEffect(() => { adoptRef.current = adopt; });
  const adoptAnswer = (r: Parameters<typeof adopt>[0]) => adoptRef.current(r);
  // The last rename's answer: the row as stored, or null when it was refused. Set before the
  // request's first await, so a click that blurred the title already sees it.
  const titleSent = useRef<Promise<Todo | null>>(Promise.resolve(null));
  // The last tags and people saves, for the same reason: a filing click blurs the field, and
  // the save it starts must land first, or a repeat's next occurrence copies the old list.
  const listsSent = useRef<{ tags: Promise<void>; people: Promise<void> }>(
    { tags: Promise.resolve(), people: Promise.resolve() });

  const dueValue = pendingDue ?? row.due;

  /** One write. `resolves` says whether it takes the item out of the inbox. */
  const patch = async (fields: Record<string, unknown>, resolves: boolean): Promise<boolean> => {
    if (busy) return false;
    setBusy(true);
    // A resolving write can unmount this card the moment it lands, and `useAutoSave` bumps
    // its generation on unmount — so a notes edit still QUEUED behind an in-flight save
    // would never be sent. `flush()` resolves on chain settle, trailing run included.
    // Cheap when there is nothing pending: it returns an already-resolved `true`.
    //
    // Deliberately NOT gated on the result. Filing is this card's one exit (todo-gtd #1548), and a
    // note the server keeps rejecting — 20k characters, say — would otherwise trap the item
    // in the inbox forever. The failure is already said twice, inline and as a toast.
    const notesOk = resolves ? await notesSave.flush() : true;
    // The date too, so filing carries a date just picked. Not gated on its result either.
    if (resolves) await dueSave.flush();
    // …and a rename: clicking here is what blurs the title, so the same gesture can send one.
    const renamed = resolves ? await titleSent.current : null;
    // …and tags or people typed just before this click. A failure is already shown.
    if (resolves) await Promise.all([listsSent.current.tags, listsSent.current.people]);
    if (notesOk) setError('');
    // What an undo row is queued from: the `todo` prop, which still holds the status and
    // context the row had before this write — but with the title the server stored. The prop
    // lags an inline rename until the parent's refetch lands, so take the newer of `row` and
    // the last rename's answer: a refused rename answers null and leaves the prior title.
    // A tie goes to the rename: an equal version is this same write.
    const title = renamed && renamed.rev >= row.at ? renamed.title : row.title;
    const before = { ...todo, title };
    try {
      // Adopt the WHOLE response. It is the authoritative row — which stops a slow refetch
      // dispatched by an earlier write from reverting a value this card has since replaced,
      // and also carries any field someone else changed in the meantime, which taking only
      // the version would silently discard.
      adoptAnswer(await updateTodo(todo.id, fields));
      // todo-gtd #2879 — the 7s undo row, guarded HERE rather than on the Done button so
      // any future completing write from this card is covered by construction.
      // `before` still holds the status the row had before this write, which is
      // exactly what undo restores.
      if (fields.status === 'done' && todo.status !== 'done') queueUndo(before);
      // todo-gtd #2925 — the same 7s row for the OTHER write that ends an item's time in
      // the inbox. `fileUnder` is the only caller that sends a context, and it
      // sends the destination status with it, so this one condition is the
      // filing write and nothing else. Queued from `before`, which still holds
      // the status AND context the row had — both are restored, because an item
      // that arrived carrying "@errands" from Quick Add must go back to
      // '@errands' and not to empty.
      else if (fields.context !== undefined && todo.status === 'inbox') queueUndo(before, 'filed');
      else if (fields.status !== undefined) dropUndo(todo.id);
      if (resolves) {
        // Deliberately stays busy — this card is spent. The parent's reload is
        // async and keeps rendering the just-filed todo until it lands;
        // re-enabling in that window would let a second write hit an item that
        // has already left the inbox — picking a context right after "Done ✓"
        // would reopen a completed (and by then already re-spawned) repeating
        // todo. Normally the reload swaps in a different head item and the
        // `key` in InboxPage remounts a fresh card. If the reload FAILS the
        // card stays disabled, which is the intended trade-off: the page also
        // renders its LoadFailed retry banner, so there is a way back.
        onProcessed();
      } else {
        setBusy(false);
        onChanged();
      }
      return true;
    } catch (e) {
      setError(apiErrorMessage(e, 'Update failed'));
      setBusy(false);
      return false;
    }
  };

  // A live view for the cleanup below, which is mount-once and would otherwise close over the
  // FIRST render — the idiom `TaskDetailPanel` uses for the same reason. A layout effect, so
  // an unmount landing between a commit and the flush still reads this render's values.
  const leaveRef = useRef({ id: todo.id, draft: notesDraft, base: row.notes, reload: onChanged });
  useLayoutEffect(() => {
    leaveRef.current = { id: todo.id, draft: notesDraft, base: row.notes, reload: onChanged };
  });
  // The card unmounts on paths it does not control: `InboxPage` keys it by todo id, so
  // promoting another queue row (or a filter that drops the head) swaps it out — and
  // `useAutoSave` bumps its generation at unmount, abandoning a QUEUED trailing run. A
  // resolving write and the Edit button both flush first; this is the door neither covers,
  // and it is the one a triage user walks through most.
  useEffect(
    () => () => {
      const { id, draft, base, reload } = leaveRef.current;
      // `sentNotes` keeps the ordinary case — unmounting while the FIRST save is still in
      // flight — from sending the same text a second time.
      if (!goneRef.current && draft !== base && draft !== sentNotes.current) {
        // CHAINED, never concurrent. Firing straight away would put this write in flight
        // alongside the one already running and hand the row to whichever commits last —
        // the very race `useAutoSave`'s single-flight exists to prevent, reintroduced at
        // the door meant to close a gap in it.
        // …and tell the parent, or its cached list keeps the pre-rescue notes: promote back
        // to this item and the box would seed from that stale copy and overwrite the text
        // this write just saved.
        const send = () => { void updateTodo(id, { notes: draft }).then(() => reload()).catch(() => {}); };
        const running = notesInFlight.current;
        if (running) void running.then(send, send);
        else send();
      }
    },
    [],
  );

  /** The only exit from the inbox: the context and the chosen destination in
   * ONE write. A context is always required — there is deliberately no "file
   * anyway" option. */
  const fileUnder = async (context: string) => {
    const value = context.trim();
    if (busy || !value) return;
    // No toast: the undo row queued by `patch` is the one notice for a filing.
    if (await patch({ context: value, status: destination }, true)) setNewContext(null);
  };

  /** Create a project mid-triage and file this item under it: the name plus
   * whatever of area / purpose / outcome was filled in. Non-resolving, like every
   * other step-2 field.
   *
   * Deliberately not `patch()`: this is TWO writes, and the interesting state is
   * the one between them. Once the project exists, a failed assignment is not
   * "creating the project failed" — reporting it that way sends the user back to
   * create a duplicate, which the unique-name constraint then rejects. */
  const createAndAssign = async (name: string) => {
    const value = name.trim();
    if (busy || !value) return;
    setBusy(true);
    setError('');
    let created: TodoProject;
    try {
      // With the todo's visibility, so filing it there keeps the hierarchy rule.
      created = await createProject({ name: value, ...newProjectFields, visibility: todo.visibility });
    } catch (e) {
      const msg = apiErrorMessage(e, 'Could not create the project');
      // Inline, so a rejected name — a duplicate, most often — is correctable
      // right there in the still-open input.
      setError(msg);
      // AND a toast, for the same reason the assignment branch below uses one:
      // this card can unmount mid-flight. A rejected POST also does not prove
      // nothing was created (the row can commit and the response be lost), so
      // refresh the pickable list too rather than leave a project that exists
      // missing from the dropdown the retry is about to collide with.
      toast.error(msg);
      setBusy(false);
      onChanged();
      return;
    }
    // The project EXISTS from here on, whatever happens next.
    setNewProject(null);
    setNewProjectFields(EMPTY_PROJECT_FIELDS);
    try {
      await updateTodo(todo.id, { project_id: created.id });
    } catch {
      // A TOAST, not this card's inline error: promoting another queue row is
      // not gated on `busy`, so the user can swap the head item while these two
      // writes are in flight — `InboxPage` keys the card by todo id, so this one
      // unmounts and an inline `setError` would land on a dead component and
      // vanish. That is precisely the case that must not go quiet: the project
      // now exists and nothing on screen would say so.
      toast.error(`Created “${created.name}”, but couldn't file this item under it — pick it from the list.`);
    }
    setBusy(false);
    onChanged(); // reloads the todo AND the project list, so the new one is pickable
  };

  // Title saves keep their own in-flight state rather than taking the card-wide
  // `busy`: clicking a button is what blurs the editor, and a shared flag would
  // swallow that very click. The two writes touch disjoint fields and the
  // service locks the row, so overlapping them is safe.
  const saveTitle = async (title: string): Promise<boolean> => {
    setError('');
    setPendingTitle(title);
    const sent = updateTodo(todo.id, { title });
    titleSent.current = sent.catch(() => null);
    try {
      // Adopt the response, like every other write on this card.
      adoptAnswer(await sent);
      onChanged();
      return true;
    } catch (e) {
      setError(apiErrorMessage(e, 'Update failed'));
      setPendingTitle(null); // never written — don't let the sheet adopt it
      return false;
    }
  };

  /** People save on blur, or at once when a suggestion is picked. Like the title, this
   * keeps off the card-wide `busy`: a click elsewhere on the card is what blurs the field,
   * and disabling the card under that click would swallow it. Non-resolving. */
  const saveList = (field: 'people' | 'tags', text: string, saved: string) => {
    const values = parseTags(text);
    if (values.join(', ') === saved) return;
    setError('');
    // Recorded before the request's first await, so a click that blurred the field sees it.
    listsSent.current[field] = (async () => {
      try {
        adoptAnswer(await updateTodo(todo.id, { [field]: values }));
        onChanged();
      } catch (e) {
        setError(apiErrorMessage(e, 'Update failed'));
      }
    })();
  };
  const savePeople = (text: string) => saveList('people', text, savedPeople);
  /** Tags save exactly as people do. */
  const saveTags = (text: string) => saveList('tags', text, savedTags);

  /** Notes commit on blur through the platform's blur-commit primitive (todo-gtd #2032) rather than
   * a sixth hand-rolled copy of it: its single-flight-with-one-trailing-run is what stops a
   * second blur from racing the first write to the same column, and it deliberately does NOT
   * take the card-wide `busy` — clicking a button is what blurs the textarea, and a shared
   * flag would swallow that very click. Non-resolving by construction: `onChanged`, never
   * `onProcessed` (todo-gtd #2402).
   *
   * No `SaveStatus` line: this card announces every other write through its own `error` line,
   * and mounting the primitive's `aria-live` beside that would give the same failure two
   * voices. */
  const notesSave = useAutoSave(
    async () => {
      if (notesDraft === row.notes) return 'nothing-to-save';
      const value = notesDraft;
      setError('');
      let saved;
      sentNotes.current = value;
      const req = updateTodo(todo.id, { notes: value });
      notesInFlight.current = req;
      try {
        saved = await req;
      } catch (e) {
        const msg = apiErrorMessage(e, 'Update failed');
        setError(msg);
        // A toast AS WELL, for the reason `createAndAssign` gives below: this card can
        // unmount mid-flight — a resolving click swaps the head item and `InboxPage` keys
        // the card by todo id — and an inline message would land on a dead component and
        // vanish, taking a paragraph the user typed with it.
        toast.error(msg);
        // Nothing reached the server, so this value is NOT "already sent" — leaving it in
        // `sentNotes` would make the unmount cleanup below skip the one write that still
        // needs making.
        sentNotes.current = null;
        throw e; // the hook classifies the failure and holds the draft for a retry
      } finally {
        if (notesInFlight.current === req) notesInFlight.current = null;
      }
      // Adopting the response moves the baseline HERE rather than when the parent's reload
      // lands: that refetch is async, so deferring would leave the field reading dirty — and
      // re-send it — for a whole round trip after it was already saved.
      adoptAnswer(saved);
      // …and the baseline for THIS field moves even when the answer was not adopted. `adopt`
      // ignores a response no newer than what the card holds, which is right for content it
      // did not write — but we know what we just sent, and leaving the baseline behind would
      // keep the field dirty, and re-sending, forever. Unless a NEWER row is already here, as
      // on the due-date path below: then that row says what the notes are, and filing this
      // text under its version would leave no later reload able to correct it. The text stays
      // in the box, unsaved, and the next blur sends it.
      const at = saved.rev;
      setRow(r => (at < r.at || r.notes === value ? r : { ...r, notes: value }));
      onChanged();
      return 'saved';
    },
    () => notesDraft !== row.notes,
  );

  /** The due date commits on BLUR, not on change, and through its own write rather than
   * `patch`'s — both for one reason (ported from CakeCRM's `commitDue`). A date input reports
   * a COMPLETE value the moment every segment parses, so it emits one on nearly every
   * keystroke: typing "12/24/2026" into an empty box yields `0002-12-24` after the year's
   * first digit, and into a populated one yields `2026-01-01` after the month's. `patch` sets
   * `busy`, which DISABLES the input, so that first write ate every remaining keystroke and
   * the truncated date was what reached the server. Committing on blur means the field is
   * never disabled while it has focus. Picking from the calendar commits on the blur that
   * follows, and a resolving write flushes it first, so filing carries the date.
   *
   * simplification: a date retyped while its first write is in flight is not sent if the card
   * unmounts before that write answers (`useAutoSave` drops a queued run at unmount); the
   * notes' parting write above is the way up. */
  const dueSave = useAutoSave(
    async () => {
      const value = dueLive.current;
      if (value === null) return 'nothing-to-save';
      // Released only while the box still holds what was sent: a date typed during this
      // write is the trailing run's to send.
      const release = () => { if (dueLive.current === value) setDue(null); };
      setError('');
      let saved;
      try {
        saved = await updateTodo(todo.id, { due_date: value || null });
        adoptAnswer(saved);
      } catch (e) {
        const msg = apiErrorMessage(e, 'Update failed');
        setError(msg);
        toast.error(msg); // same unmount reasoning as the notes save
        release(); // nothing was written, so don't go on showing a date the server never took
        throw e;
      }
      // The baseline for this field moves even when the answer was not adopted, as it does for
      // the notes — unless a NEWER row is already here: then that row says what the date is,
      // and putting this one under its version would leave no later reload able to correct it.
      // A tie goes to this answer: an equal `rev` is this same write.
      const at = saved.rev;
      setRow(r => (at < r.at || r.due === value ? r : { ...r, due: value }));
      release();
      onChanged();
      return 'saved';
    },
    () => dueLive.current !== null,
  );

  // What the user believes this todo is called right now. Once the reload
  // lands, `todo.title` catches up and the merge is a no-op.
  // …and the notes it carries are the ones in the box, for the same reason: blur
  // then click means "Edit" opens the sheet on a card whose notes were only just
  // typed, and the sheet writes back every field it was handed.
  // What the sheet is handed: this card's best view of the row, never the lagging prop. All
  // three of these can be ahead of `todo` mid-refetch, and the sheet writes back every field
  // it is given. (Star and project are not here: they are written straight through `patch`
  // and never rendered optimistically, so the prop is the only view of them the card has.)
  const current = {
    ...todo,
    title: pendingTitle ?? row.title,
    notes: notesDraft,
    due_date: dueValue || null,
    people: parseTags(peopleDraft),
    tags: parseTags(tagsDraft),
  };
  // The same, as of the latest render. Edit opens the sheet only once its writes have
  // answered, and the card stays editable meanwhile — so the sheet is handed what is on the
  // card when it opens, not what was there at the click.
  const currentRef = useRef(current);
  useLayoutEffect(() => { currentRef.current = current; });

  return (
    <div className="rounded-xl border border-sf-line-strong bg-sf-card p-4 sm:p-5 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <InlineTitle
          title={current.title}
          label="Todo title"
          disabled={busy}
          onSave={saveTitle}
          className="font-display text-lg font-semibold text-sf-ink"
        />
        <button
          type="button"
          disabled={busy}
          onClick={() => void patch({ star: !todo.star }, false)}
          className={`shrink-0 text-xl leading-none disabled:opacity-50 ${todo.star ? 'text-sf-amber' : 'text-sf-line-strong hover:text-sf-amber'}`}
          aria-label="Star as today priority"
        >
          ★
        </button>
      </div>
      {todo.source === 'agent' && (
        <p className="mt-1 text-xs">
          <SourceLabel todo={todo} />
        </p>
      )}

      {/* Step 1 — where it's headed. Selecting is local: the item stays put
          until step 3 gives it a context. */}
      <div className="mt-5">
        <StepBar n={1}>What kind of action?</StepBar>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {DESTINATIONS.map(d => {
            const on = d.status === destination;
            return (
              <button
                key={d.status}
                type="button"
                disabled={busy}
                aria-pressed={on}
                onClick={() => setDestination(d.status)}
                className={`${destCls} ${on
                  ? 'border-sf-accent bg-sf-accent-soft font-semibold text-sf-ink'
                  : 'border-sf-line-strong bg-sf-card text-sf-ink-dim hover:bg-sf-hover'}`}
              >
                {d.label}
              </button>
            );
          })}
        </div>
        <button
          type="button"
          disabled={busy}
          onClick={() => void patch({ status: 'done' }, true)}
          title="It took under 2 minutes — done"
          className="mt-2 rounded-lg border border-sf-green px-3 py-1.5 text-sm font-display text-sf-green-text disabled:opacity-50 hover:bg-sf-green/10"
        >
          Took 2 minutes — Done ✓
        </button>
      </div>

      {/* Step 2 — optional enrichment. Nothing here leaves the inbox. */}
      <div className="mt-5">
        <StepBar n={2}>Add detail (optional)</StepBar>
        <div className="flex flex-wrap items-end gap-2">
          {newProject === null ? (
            <div>
            <span className={fieldCls}>Project</span>
            <select
              value={todo.project_id ?? ''}
              disabled={busy}
              onChange={e => {
                const v = e.target.value;
                if (v === NEW_PROJECT) { setNewProject(''); return; }
                void patch({ project_id: v ? Number(v) : null }, false);
              }}
              className={inputCls}
              aria-label="Project"
            >
              <option value="">No project</option>
              {projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
              <option value={NEW_PROJECT}>+ New project…</option>
            </select>
            </div>
          ) : (
            <form
              onSubmit={e => { e.preventDefault(); void createAndAssign(newProject); }}
              className="flex w-full flex-wrap items-center gap-2"
            >
              <input
                value={newProject}
                onChange={e => setNewProject(e.target.value)}
                placeholder="New project name"
                autoFocus
                disabled={busy}
                className={`${inputCls} border-sf-accent`}
                aria-label="New project name"
              />
              <button
                type="submit"
                disabled={busy || !newProject.trim()}
                className="rounded-lg border border-sf-line-strong bg-sf-card px-3 py-1.5 text-sm font-display text-sf-ink hover:bg-sf-hover disabled:opacity-50"
              >
                Create
              </button>
              {/* Cancel leaves project_id alone — the select is driven by the
                  todo, so the prior choice comes back untouched. It DOES clear
                  the error: that message belongs to the attempt being abandoned,
                  and leaving it up reads as a failure of whatever comes next. */}
              <button
                type="button"
                disabled={busy}
                onClick={() => { setNewProject(null); setNewProjectFields(EMPTY_PROJECT_FIELDS); setError(''); }}
                className={`${linkCls} text-sf-ink-dim hover:text-sf-ink`}
              >
                Cancel
              </button>
              <ProjectFields values={newProjectFields} areas={areas} disabled={busy}
                             onChange={setNewProjectFields} />
            </form>
          )}
          {/* A native date input ignores `placeholder` — browsers render their own
              empty state instead — so the "Add due date" cue is an opaque overlay laid
              over the whole control, exactly as a real placeholder would fill the field.
              It goes away as soon as there is a value or the field takes focus, so the
              native editor (and its calendar button) is never hidden while it is being
              used (issue todo-gtd #2351).

              Two measurements, not guesses — a Playwright pass over the built CSS in
              both engines: WebKit's empty date input is only ~96px wide and renders
              TODAY'S date greyed rather than mm/dd/yyyy, so a partial overlay left
              "…026" peeking out and the cue wrapped onto two lines. Hence `inset-px`
              (cover all of it, in every engine) and the width floor. */}
          <div>
          <span className={fieldCls}>Due date</span>
          <span className="relative flex">
            <input
              type="date"
              value={dueValue}
              disabled={busy}
              onFocus={() => setDueFocused(true)}
              onBlur={() => {
                setDueFocused(false);
                // Typed back to the date the row already holds: nothing to write, so stop
                // shadowing the row. Not while a save is in flight — the row is about to move.
                if (pendingDue === row.due && dueSave.status !== 'saving') setDue(null);
                else dueSave.commit();
              }}
              // Shown at once, written on blur — `dueSave` says why. Nothing here disables
              // the input, so the user can finish typing the date.
              onChange={e => setDue(e.target.value)}
              className={`${inputCls} min-w-40`}
              aria-label="Due date"
            />
            {/* Keyed off `dueValue`, not the raw prop: without the optimistic value the field
                blanks the instant the write is sent and the cue flashes back over the date
                just chosen, for the whole length of the refetch. `dueFocused` is the second
                half — it keeps the cue off the native editor mid-pick. */}
            {!dueValue && !dueFocused && (
              <span
                aria-hidden="true"
                className="pointer-events-none absolute inset-px flex items-center whitespace-nowrap rounded-lg bg-sf-card pl-2 text-sm text-sf-ink-dim"
              >
                Add due date
              </span>
            )}
          </span>
          </div>
          <button
            type="button"
            disabled={busy || editPending}
            onClick={() => {
              // Clicking Edit is what blurs the textarea, so a notes write may be in flight —
              // and the sheet writes `notes` too. Without this the card's older PUT can land
              // after the sheet's and overwrite it. Opened regardless of the result: a draft
              // the server rejected is exactly what the sheet is there to rescue. The due
              // date is written on that same blur and the sheet writes it too, so it waits
              // on both.
              //
              // The whole card is locked for the wait, not just this button: a star or
              // project change made in it would start a write the sheet never sees — it
              // opens on the old value, and its full-field save puts that back.
              setEditPending(true);
              setBusy(true);
              void Promise.all([notesSave.flush(), dueSave.flush()]).then(() => {
                setEditPending(false);
                setBusy(false);
                onEdit(currentRef.current);
              });
            }}
            className={`${linkCls} text-sf-ink-dim hover:text-sf-ink`}
          >
            Edit
          </button>
          {/* Nothing is ever deleted: Drop archives it (status 'dropped'), and the
              Done page's Dropped tab is where it can be brought back from. */}
          <button
            type="button"
            disabled={busy}
            onClick={() => void patch({ status: 'dropped' }, true)}
            className={`${linkCls} text-sf-accent-text hover:text-sf-ink`}
          >
            Drop
          </button>
        </div>
        {/* Project fields appear only once there is a project to describe: the one
            picked above (edits save to the project itself), or the new one being
            named (they are created with it). No project, no fields. */}
        {project && newProject === null && (
          <div className="mt-2">
            <ProjectDetails key={project.id} project={project} areas={areas} disabled={busy}
                            onSaved={onChanged} />
          </div>
        )}
        {/* Notes belong to clarifying, not only to the full editor (todo-gtd #2402) — jot the
            link or phone number without leaving triage. Saved on blur, non-resolving,
            so the item stays in the inbox. This replaces the read-only preview that
            used to sit under the title. */}
        <span className={`${fieldCls} mt-3`}>Notes</span>
        <textarea
          value={notesDraft}
          disabled={busy}
          onChange={e => setNotesDraft(e.target.value)}
          onBlur={notesSave.commit}
          placeholder="Links, numbers, anything you'll want when you do it"
          className={`${inputCls} block min-h-16 w-full`}
          aria-label="Notes"
        />
        {/* Who it involves — worth settling while clarifying, since "who" is half of
            what makes a waiting-for or an agenda item findable later. */}
        <span className={`${fieldCls} mt-3`}>Tags</span>
        <PeopleInput
          label="Tags"
          placeholder="errand, quick, house"
          className={`${inputCls} block w-full`}
          value={tagsDraft}
          disabled={busy}
          onChange={setTagsDraft}
          suggestions={knownTags}
          onBlur={() => void saveTags(tagsDraft)}
          onPick={value => void saveTags(value)}
        />
        <span className={`${fieldCls} mt-3`}>People</span>
        <PeopleInput
          label="People"
          className={`${inputCls} block w-full`}
          value={peopleDraft}
          disabled={busy}
          onChange={setPeopleDraft}
          suggestions={knownPeople}
          onBlur={() => void savePeople(peopleDraft)}
          onPick={value => void savePeople(value)}
        />
      </div>

      {/* Step 3 — the last step. Picking a context files it and clears the inbox. */}
      <div className="mt-5 border-t border-sf-line pt-4">
        <StepBar n={3} required>Last step — set context</StepBar>
        <p className="mb-2 text-sm text-sf-ink-dim">
          Where can you actually do this? Every item needs a context before it leaves the
          inbox. Choosing one files it under{' '}
          <span className="font-semibold text-sf-ink">{dest.list}</span> and clears it out of
          your inbox — do it last.
        </p>
        {newContext === null ? (
          <div className="flex flex-wrap items-center gap-2">
            <select
              value=""
              disabled={busy}
              onChange={e => {
                const v = e.target.value;
                if (!v) return;
                if (v === NEW_CONTEXT) { setNewContext(''); return; }
                const picked = options[Number(v)];
                if (picked) void fileUnder(picked);
              }}
              className={`${inputCls} border-sf-accent`}
              aria-label="Set context and file this todo"
            >
              <option value="">Set context…</option>
              {options.map((c, i) => <option key={c} value={i}>{c}</option>)}
              <option value={NEW_CONTEXT}>+ New context…</option>
            </select>
            {todo.context && <span className="text-xs text-sf-ink-dim">currently {todo.context}</span>}
          </div>
        ) : (
          <form
            onSubmit={e => { e.preventDefault(); void fileUnder(newContext); }}
            className="flex flex-wrap items-center gap-2"
          >
            <input
              value={newContext}
              onChange={e => setNewContext(e.target.value)}
              placeholder="@home, @calls, @errands…"
              autoFocus
              disabled={busy}
              className={`${inputCls} border-sf-accent`}
              aria-label="New context"
            />
            <button
              type="submit"
              disabled={busy || !newContext.trim()}
              className="rounded-lg bg-sf-accent px-4 py-1.5 text-sm font-display text-sf-accent-ink hover:bg-sf-accent-dark disabled:opacity-50"
            >
              File →
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => { setNewContext(null); setError(''); }}
              className={`${linkCls} text-sf-ink-dim hover:text-sf-ink`}
            >
              Cancel
            </button>
          </form>
        )}
      </div>
      {error && <p className="mt-3 text-sm text-sf-accent-text">{error}</p>}
    </div>
  );
}

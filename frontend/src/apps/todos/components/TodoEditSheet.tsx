import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router';
import { apiErrorMessage } from '../errors';
import { createTodo, projectIdFor, updateTodo } from '../api';
import { useMe } from '../me';
import { todoPath } from '../menu';
import { dropUndo, hasPendingFiling, queueUndo } from '../undoQueue';
import { REPEAT_OPTIONS, SOURCE_LABEL, STATUS_META, TODO_STATUS_ORDER } from '../constants';
import type { ItemIn, ItemPatch, Todo, TodoProject, TodoStatus, Visibility } from '../types';
import { useListFilters } from '../useTodoMeta';
import { memberName, parseTags, withOwnArea } from '../util';
import { PeopleInput } from './PeopleInput';
import { nextActionCopyText, todoCopyText } from '../copyText';
import { CopyButton } from './CopyButton';
import { SharingFields } from './Sharing';

const NEW_PROJECT = '__new__';
// The context picker's option values are INDICES into `contextOptions`, never the
// context strings — the same reason TriageCard.tsx gives: a context a user really
// named `__new__` would otherwise collide with the sentinel and be unselectable.
const NEW_CONTEXT = '__new__';

interface Props {
  /** null = create mode */
  todo: Todo | null;
  /** Defaults for create mode (e.g. project detail's inline add, a record's quick add). */
  defaults?: Partial<Pick<Todo, 'status' | 'project_id' | 'visibility' | 'entity_type' | 'entity_id'>>;
  projects: TodoProject[];
  contexts: string[];
  onClose: () => void;
  onSaved: () => void;
  /** Render in the page's flow (a todo's own page) instead of as a modal sheet. */
  asPage?: boolean;
}

const inputCls =
  'w-full rounded-lg border border-sf-line-strong bg-sf-card px-3 py-2 text-base sm:text-sm text-sf-ink focus:border-sf-accent focus:outline-none';
const labelCls = 'block text-xs font-display font-semibold text-sf-ink-dim mb-1';

/** Full-field editor — centered modal on desktop, bottom sheet on mobile. */
export function TodoEditSheet({ todo, defaults, projects, contexts, onClose, onSaved, asPage }: Props) {
  const [title, setTitle] = useState(todo?.title ?? '');
  const [notes, setNotes] = useState(todo?.notes ?? '');
  const [status, setStatus] = useState<TodoStatus>(todo?.status ?? defaults?.status ?? 'inbox');
  const [projectSel, setProjectSel] = useState<string>(
    String(todo?.project_id ?? defaults?.project_id ?? ''),
  );
  const [newProject, setNewProject] = useState('');
  const [context, setContext] = useState(todo?.context ?? '');
  // true = the picker has been swapped for the "type a brand new one" input.
  const [addingContext, setAddingContext] = useState(false);
  const [tags, setTags] = useState((todo?.tags ?? []).join(', '));
  const [people, setPeople] = useState((todo?.people ?? []).join(', '));
  // The todo's OWN area; '' leaves it to the project's.
  const [areaSel, setAreaSel] = useState(String(todo?.area_id ?? ''));
  const [due, setDue] = useState(todo?.due_date ?? '');
  const [revisit, setRevisit] = useState(todo?.revisit_on ?? '');
  const meta = useListFilters();
  const [repeat, setRepeat] = useState(todo?.repeat ?? '');
  const [everyN, setEveryN] = useState(
    todo?.repeat?.startsWith('every:') ? todo.repeat.slice(6) : '3',
  );
  const [star, setStar] = useState(todo?.star ?? false);
  const [autoStar, setAutoStar] = useState(todo?.auto_star_on_due ?? false);
  // Who sees it and who it is for. A new todo starts at the install's default visibility,
  // which arrives with the filters, so null means "the default" until the user picks.
  const [visibilityPick, setVisibility] = useState<Visibility | null>(todo?.visibility ?? defaults?.visibility ?? null);
  const visibility = visibilityPick ?? meta?.default_visibility ?? 'private';
  const [assignee, setAssignee] = useState<number | null>(todo?.assignee_user_id ?? null);
  const me = useMe();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  // The SELECTED context always gets an option, whether or not the shared meta lists it.
  // Two ways it can be missing: the meta loads async (so a todo's own context isn't there
  // on the first paint), and a refresh while this sheet is open can DROP a context the user
  // just picked. Either way an option list without the current selection renders a select
  // matching no option, while `save()` still submits the hidden string — the control and the
  // payload disagreeing is worse than an extra option.
  //
  // While the create input is open the todo's original stands in, so the list does not
  // reshuffle on every keystroke of a name being typed (the select is showing the sentinel
  // then, so its contents do not matter).
  const contextOptions = useMemo(() => {
    const known = contexts.filter(Boolean);
    const own = (addingContext ? (todo?.context ?? '') : context).trim();
    return own && !known.includes(own) ? [own, ...known] : known;
  }, [contexts, context, addingContext, todo?.context]);

  // Derived every render from the context STRING rather than held in state: the meta
  // list arrives after the first render, and an index frozen at mount would then point
  // at a different context.
  const contextSel = addingContext
    ? NEW_CONTEXT
    : (context ? String(contextOptions.indexOf(context)) : '');

  // Same rule as contexts: the todo's own area always has an option, even once
  // archived (the pickers only list active areas).
  const areaOptions = useMemo(
    () => withOwnArea(meta?.areas ?? [], todo?.area_id, todo?.area_name),
    [meta?.areas, todo?.area_id, todo?.area_name]);
  const projectArea = projects.find(p => String(p.id) === projectSel)?.area_name;

  useEffect(() => {
    if (asPage) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose, asPage]);

  const isEvery = repeat === 'every' || repeat.startsWith('every:');
  const effectiveRepeat = isEvery ? `every:${everyN || '1'}` : repeat;

  const save = async () => {
    if (!title.trim() || busy) return;
    setBusy(true);
    setError('');
    const fields: ItemPatch = {
      title: title.trim(),
      notes,
      context: context.trim(),
      tags: parseTags(tags),
      people: parseTags(people),
      area_id: areaSel ? Number(areaSel) : null,
      status,
      star,
      due_date: due || null,
      revisit_on: revisit || null,
      repeat: effectiveRepeat,
      // Clearing the repeat rule clears the rule that depends on it, so a todo
      // can never carry a hidden auto-star that reappears if it repeats again.
      auto_star_on_due: effectiveRepeat ? autoStar : false,
      assignee_user_id: assignee,
    };
    if (visibilityPick !== null) fields.visibility = visibilityPick;
    try {
      // A new project is made first, with the todo's visibility, so the pair keeps the
      // hierarchy rule by construction.
      fields.project_id = projectSel === NEW_PROJECT
        ? (newProject.trim() ? await projectIdFor(newProject.trim(), projects, { visibility }) : null)
        : (projectSel ? Number(projectSel) : null);
      if (todo) {
        await updateTodo(todo.id, fields);
        // todo-gtd #2879 — edits only. Creating a todo that is already done has no prior
        // status to restore, so there is nothing to undo.
        // `effectiveRepeat`, not `todo.repeat`: the backend spawns the successor
        // from the POST-update row, so a save that sets done AND edits the repeat
        // rule completed under the NEW rule. Stamping the old one makes undo's
        // duplicate-occurrence warning wrong in both directions.
        if (status === 'done' && todo.status !== 'done') {
          queueUndo({ ...todo, repeat: effectiveRepeat });
        }
        // todo-gtd #2925 — this sheet FILES an inbox item too. `TriageCard`'s Edit button
        // opens it on the very item being triaged, so picking a context and a
        // destination here sends the same write step 3 sends, with the same
        // mis-click behind it; withholding the row on one of the two routes out of
        // the inbox makes the affordance silently conditional. `todo` still holds
        // the pre-write status and context, which is what undo restores.
        else if (todo.status === 'inbox' && status !== 'inbox' && context.trim()) {
          queueUndo(todo, 'filed');
        }
        // A pending row is invalidated by a write that MOVES the todo off where the
        // queued write put it — the sheet is reachable inside the 7s window (Search
        // keeps completed rows on screen), and undoing afterwards would overwrite a
        // decision the user has since deliberately made.
        //
        // WHICH field moved it depends on what is pending, which is why this is not
        // simply `status !== 'done'` and not simply `status !== todo.status`. The
        // first was an accurate proxy only while `done` was the one queued kind: an
        // unchanged save of a done todo matched neither branch, but a todo-gtd #2925 filing
        // row sits at a NON-done status, so that proxy matched every unrelated save
        // and adding a due date inside the window silently cancelled an undo still
        // on screen. The second misses the other half — a filing restores the
        // CONTEXT too, so re-filing the item under a different context here is a
        // later decision that must retire the offer, where the very same edit leaves
        // a mark-done row (which puts back only the status) perfectly valid.
        else if (
          status !== todo.status
          || (hasPendingFiling(todo.id) && context.trim() !== todo.context)
        ) {
          dropUndo(todo.id);
        }
      } else {
        const link = defaults?.entity_type && defaults.entity_id
          ? { entity_type: defaults.entity_type, entity_id: defaults.entity_id } : {};
        await createTodo({ ...fields, ...link } as ItemIn);
      }
      onSaved();
      onClose();
    } catch (e) {
      setError(apiErrorMessage(e, 'Save failed'));
      setBusy(false);
    }
  };

  // Copy reads the LIVE form, not `todo` — you can retype the action and copy
  // it before saving, and what lands on the clipboard is what is on screen.
  // Lazy (called on click) so the string is only built when it is wanted.
  const copyFields = () => ({
    title, notes, status,
    projectName: projectSel === NEW_PROJECT
      ? newProject.trim() || null
      : projects.find(p => String(p.id) === projectSel)?.name ?? null,
    context, tags: parseTags(tags),
    dueDate: due || null, repeat: effectiveRepeat, star,
  });

  return (
    <div
      className={asPage ? '' : 'fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-sf-scrim p-0 sm:p-4'}
      onMouseDown={e => { if (!asPage && e.target === e.currentTarget) onClose(); }}
    >
      <div className={asPage
        ? 'rounded-xl border border-sf-line bg-sf-card p-5'
        : 'max-h-[92dvh] w-full sm:max-w-lg overflow-y-auto rounded-t-2xl sm:rounded-2xl border border-sf-line bg-sf-card p-5 shadow-lg'}>
        <div className="flex items-center justify-between gap-3">
          <h2 className="font-display text-lg font-bold text-sf-ink">
            {todo ? 'Edit todo' : 'New todo'}
          </h2>
          {/* Whole todo — the heading names what this button copies. */}
          {title.trim() && (
            <CopyButton text={() => todoCopyText(copyFields())} label="Copy the whole todo" />
          )}
        </div>

        <div className="mt-4 space-y-3">
          <div>
            <div className="mb-1 flex items-center justify-between gap-3">
              <label className={`${labelCls} mb-0`} htmlFor="tgtd-title">
                What&rsquo;s the next action?
              </label>
              {/* Just this line — the common case is pasting the action itself
                  into a message, without the status/project scaffolding. */}
              {title.trim() && (
                <CopyButton text={() => nextActionCopyText(title)} label="Copy just the next action" />
              )}
            </div>
            <input id="tgtd-title" className={inputCls} value={title} autoFocus={!asPage}
                   onChange={e => setTitle(e.target.value)} />
          </div>
          <div>
            <label className={labelCls} htmlFor="tgtd-notes">Notes</label>
            <textarea id="tgtd-notes" className={`${inputCls} min-h-20`} value={notes}
                      onChange={e => setNotes(e.target.value)} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={labelCls} htmlFor="tgtd-status">Status</label>
              <select id="tgtd-status" className={inputCls} value={status}
                      onChange={e => setStatus(e.target.value as TodoStatus)}>
                {TODO_STATUS_ORDER.map(s => (
                  <option key={s} value={s}>{STATUS_META[s].label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className={labelCls} htmlFor="tgtd-due">Due date</label>
              <input id="tgtd-due" type="date" className={inputCls} value={due}
                     onChange={e => setDue(e.target.value)} />
            </div>
            <div>
              <label className={labelCls} htmlFor="tgtd-project">Project</label>
              <select id="tgtd-project" className={inputCls} value={projectSel}
                      onChange={e => setProjectSel(e.target.value)}>
                <option value="">No project</option>
                {projects.map(p => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
                <option value={NEW_PROJECT}>+ New project…</option>
              </select>
              {projectSel === NEW_PROJECT && (
                <input className={`${inputCls} mt-2`} placeholder="New project name"
                       value={newProject} onChange={e => setNewProject(e.target.value)} />
              )}
            </div>
            <div>
              <label className={labelCls} htmlFor="tgtd-context">Context</label>
              {/* A <select>, not an <input list>/<datalist>: mobile browsers do not
                  reliably render a datalist on a populated text input, so the picker
                  was invisible until the field was cleared (todo-gtd #2352). This is the same
                  select-plus-escape-hatch shape the Inbox triage card already uses,
                  and the shape Status/Project/Repeat use in this very form. */}
              <select id="tgtd-context" className={inputCls} value={contextSel}
                      onChange={e => {
                        const v = e.target.value;
                        if (v === NEW_CONTEXT) { setAddingContext(true); setContext(''); return; }
                        setAddingContext(false);
                        setContext(v ? contextOptions[Number(v)] ?? '' : '');
                      }}>
                <option value="">No context</option>
                {contextOptions.map((c, i) => <option key={c} value={i}>{c}</option>)}
                <option value={NEW_CONTEXT}>+ New context…</option>
              </select>
              {addingContext && (
                <input className={`${inputCls} mt-2`} placeholder="@calls"
                       aria-label="New context" value={context}
                       onChange={e => setContext(e.target.value)} />
              )}
            </div>
            <div>
              <label className={labelCls} htmlFor="tgtd-repeat">Repeat</label>
              <select id="tgtd-repeat" className={inputCls}
                      value={isEvery ? 'every' : repeat}
                      onChange={e => setRepeat(e.target.value)}>
                {REPEAT_OPTIONS.map(o => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
                <option value="every">Every N days…</option>
              </select>
              {isEvery && (
                <input type="number" min={1} max={9999} value={everyN}
                       onChange={e => setEveryN(e.target.value)}
                       className={`${inputCls} mt-2`} placeholder="N days" />
              )}
            </div>
            <div>
              <label className={labelCls} htmlFor="tgtd-tags">Tags (comma-separated)</label>
              <input id="tgtd-tags" className={inputCls} value={tags}
                     onChange={e => setTags(e.target.value)} />
            </div>
            <div>
              <label className={labelCls} htmlFor="tgtd-people">People (comma-separated)</label>
              <PeopleInput id="tgtd-people" className={inputCls} value={people}
                           onChange={setPeople} suggestions={meta?.people ?? []} />
            </div>
            <div>
              <label className={labelCls} htmlFor="tgtd-area">Area</label>
              <select id="tgtd-area" className={inputCls} value={areaSel}
                      onChange={e => setAreaSel(e.target.value)}>
                <option value="">{projectArea ? `Same as project (${projectArea})` : 'No area'}</option>
                {areaOptions.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
              </select>
            </div>
            {/* Offered on someday items — and kept visible wherever a date is already
                set, so it can always be seen and cleared. */}
            {(status === 'someday_maybe' || revisit) && (
              <div>
                <label className={labelCls} htmlFor="tgtd-revisit">Bring back on…</label>
                <input id="tgtd-revisit" type="date" className={inputCls} value={revisit}
                       onChange={e => setRevisit(e.target.value)} />
              </div>
            )}
            <SharingFields idPrefix="tgtd" inline visibility={visibility} assignee={assignee}
                           ownerId={todo?.owner_user_id ?? me.id} members={meta?.members ?? []}
                           onChange={p => {
                             if (p.visibility) setVisibility(p.visibility);
                             if (p.assignee_user_id !== undefined) setAssignee(p.assignee_user_id);
                           }} />
          </div>
          <label className="flex items-center gap-2 text-sm text-sf-ink">
            <input type="checkbox" checked={star} onChange={e => setStar(e.target.checked)}
                   className="h-4 w-4 accent-sf-amber" />
            ★ Today priority
          </label>
          {effectiveRepeat && (
            <div>
              <label className="flex items-center gap-2 text-sm text-sf-ink">
                <input type="checkbox" checked={autoStar}
                       onChange={e => setAutoStar(e.target.checked)}
                       className="h-4 w-4 accent-sf-amber" />
                ★ Star the next occurrence when it comes due today
              </label>
              <p className="mt-1 pl-6 text-xs text-sf-ink-dim">
                Applies when completing this makes the next one due today, so a routine
                finished late lands straight on the Today list.
              </p>
            </div>
          )}
        </div>

        {todo && (
          <p className="mt-3 text-xs text-sf-ink-dim">
            {todo.visibility === 'team' && `Owner: ${todo.owner_name ?? memberName(meta?.members, todo.owner_user_id)} · `}
            Source: {SOURCE_LABEL[todo.source]} · Created {new Date(todo.created_at).toLocaleDateString()}
            {todo.completed_at && ` · Completed ${new Date(todo.completed_at).toLocaleDateString()}`}
          </p>
        )}
        {error && <p role="alert" className="mt-2 text-sm text-sf-accent-text">{error}</p>}

        <div className="mt-5 flex items-center gap-2">
          <button type="button" onClick={() => void save()} disabled={!title.trim() || busy}
                  className="rounded-lg bg-sf-accent px-4 py-2 text-sm font-display text-sf-accent-ink hover:bg-sf-accent-dark disabled:opacity-40">
            {todo ? 'Save' : 'Add'}
          </button>
          {!asPage && <button type="button" onClick={onClose}
                  className="rounded-lg border border-sf-line-strong bg-sf-card px-4 py-2 text-sm font-display text-sf-ink hover:bg-sf-hover">
            Cancel
          </button>}
          {todo && !asPage && (
            <Link to={todoPath(`/items/${todo.id}`)} onClick={onClose}
                  className="ml-auto text-sm text-sf-accent-text">
              Open page: notes, files, history
            </Link>
          )}
        </div>
      </div>
    </div>
  );
}

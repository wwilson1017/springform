/**
 * Saved views for one screen ("surface"): apply, save the current state as a new view, rename,
 * overwrite, share or unshare, delete. The host owns the state (`value`, `onChange`); this bar
 * stores it as `{schema_version, value}` and refuses to apply a view saved under another
 * `schemaVersion` (see savedViews.ts).
 *
 * Every edit sends the view's server `version`; a 409 `stale_view` means someone (or another
 * tab) changed it since this list loaded, so the list reloads and the user retries on fresh data.
 *
 * Lifted in behaviour from CakeCRM's SavedViewsMenu: fetch on open, never on mount; a response
 * from a superseded request is dropped; `can_edit` is the server's answer, so no auth context.
 */
import { useEffect, useRef, useState } from 'react';
import { ApiError, del, fetchJson, patchJson, postJson } from '../api/client';
import { confirmDialog } from '../../shared/confirm';
import { IconChevronDown } from '../../shared/icons';
import { toast } from '../../shared/toast';
import { isStaleView, viewPayload, viewValue } from './savedViews';
import type { SavedView } from './types';
import { BTN_LINK, BTN_SECONDARY, INPUT, errorText } from './ui';

export interface SavedViewBarProps<T> {
  /** `<area>.<screen>`, e.g. `core.reminders`. */
  surface: string;
  entityType?: string;
  /** The screen's current state, saved as a view's value. */
  value: T;
  /** Applies a saved view's value to the screen. */
  onChange: (value: T) => void;
  /** Bump when the shape of `value` changes; views saved under another version are refused. */
  schemaVersion: number;
}

const VIEWS = '/api/core/views';
const CONFLICTS: Record<string, string> = {
  duplicate_name: 'You already have a view with that name.',
  too_many_views: 'This screen has too many saved views. Delete one first.',
};

export function SavedViewBar<T>({ surface, entityType, value, onChange, schemaVersion }: SavedViewBarProps<T>) {
  const [open, setOpen] = useState(false);
  const [views, setViews] = useState<SavedView[] | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [applied, setApplied] = useState<{ id: number; name: string } | null>(null);
  const [form, setForm] = useState<{ kind: 'save' } | { kind: 'rename'; view: SavedView } | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const seq = useRef(0);
  const wrapper = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => { if (!wrapper.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [open]);

  function load() {
    const mine = ++seq.current;
    setLoadError(false);
    fetchJson<SavedView[]>(`${VIEWS}?${new URLSearchParams({ surface })}`).then(
      list => { if (mine === seq.current) setViews(list); },
      () => { if (mine === seq.current) setLoadError(true); },
    );
  }

  function toggle() {
    setOpen(o => !o);
    setForm(null);
    setFormError(null);
    if (!open) load();
  }

  function apply(view: SavedView) {
    const next = viewValue<T>(view, schemaVersion);
    if (next === null) return;
    onChange(next);
    setApplied({ id: view.id, name: view.name });
    setOpen(false);
  }

  /** One shape for every write: busy guard, reload on success, stale and name conflicts handled. */
  async function run(work: () => Promise<unknown>, done: string, failure: string, ownsForm: boolean) {
    if (busy) return;
    setBusy(true);
    try {
      await work();
      toast.success(done);
      if (ownsForm) { setForm(null); setFormError(null); }
      load();
    } catch (err) {
      const detail = err instanceof ApiError && err.status === 409 ? err.detail : null;
      if (detail === 'stale_view') {
        toast.info('This view was changed somewhere else. The list is reloaded; try again.');
        if (ownsForm) setForm(null);
        load();
      } else if (detail && ownsForm) {
        setFormError(CONFLICTS[detail] ?? detail);
      } else {
        toast.error(detail ? CONFLICTS[detail] ?? detail : errorText(err, failure));
      }
    } finally {
      setBusy(false);
    }
  }

  const saveAs = (name: string) => run(async () => {
    const view = await postJson<SavedView>(VIEWS, { surface, name, payload: viewPayload(value, schemaVersion), ...(entityType ? { entity_type: entityType } : {}) });
    setApplied({ id: view.id, name: view.name });
  }, 'View saved.', "Couldn't save the view.", true);

  const rename = (view: SavedView, name: string) => run(async () => {
    await patchJson(`${VIEWS}/${view.id}`, { version: view.version, name });
    if (applied?.id === view.id) setApplied({ id: view.id, name });
  }, 'View renamed.', "Couldn't rename the view.", true);

  async function overwrite(view: SavedView) {
    if (view.is_shared && !await confirmDialog({
      title: 'Update shared view',
      message: `Replace "${view.name}" with what this screen shows now? Everyone it is shared with sees the change.`,
      confirmLabel: 'Update',
    })) return;
    await run(() => patchJson(`${VIEWS}/${view.id}`, { version: view.version, payload: viewPayload(value, schemaVersion) }),
      'View updated.', "Couldn't update the view.", false);
  }

  async function remove(view: SavedView) {
    if (!await confirmDialog({ title: 'Delete saved view', message: `Delete "${view.name}"?`, confirmLabel: 'Delete', danger: true })) return;
    await run(async () => {
      await del(`${VIEWS}/${view.id}`);
      if (applied?.id === view.id) setApplied(null);
    }, 'View deleted.', "Couldn't delete the view.", false);
  }

  return (
    <div ref={wrapper} className="relative" onKeyDown={e => { if (e.key === 'Escape') setOpen(false); }}>
      <button type="button" aria-haspopup="dialog" aria-expanded={open} onClick={toggle}
        className={`${BTN_SECONDARY} flex max-w-56 items-center gap-1.5`}>
        <span className="truncate">{applied ? `View: ${applied.name}` : 'Saved views'}</span>
        <IconChevronDown size={14} aria-hidden />
      </button>
      {open && (
        <div role="dialog" aria-label="Saved views"
          className="absolute left-0 z-30 mt-1 w-80 max-w-[calc(100vw-2rem)] rounded-md border border-sf-line-strong bg-sf-card shadow-lg">
          <div className="border-b border-sf-line p-3">
            {form?.kind === 'save'
              ? <NameForm initial="" submit="Save" busy={busy} error={formError} onSubmit={name => void saveAs(name)} onCancel={() => { setForm(null); setFormError(null); }} />
              : <button type="button" className={BTN_LINK} onClick={() => { setForm({ kind: 'save' }); setFormError(null); }}>Save current view as…</button>}
          </div>
          {loadError ? (
            <p className="m-0 p-3 text-xs text-sf-ink-mute">Couldn't load saved views. <button type="button" className={BTN_LINK} onClick={load}>Retry</button></p>
          ) : !views ? (
            <p className="m-0 p-3 text-xs text-sf-ink-dim">Loading…</p>
          ) : views.length === 0 ? (
            <p className="m-0 p-3 text-xs text-sf-ink-dim">No saved views yet.</p>
          ) : (
            <ul className="m-0 max-h-80 list-none overflow-y-auto p-0">
              {views.map(view => {
                const stale = isStaleView(view, schemaVersion);
                return (
                  <li key={view.id} className="border-b border-sf-line px-3 py-2 last:border-b-0">
                    {form?.kind === 'rename' && form.view.id === view.id ? (
                      <NameForm initial={view.name} submit="Rename" busy={busy} error={formError}
                        onSubmit={name => void rename(view, name)} onCancel={() => { setForm(null); setFormError(null); }} />
                    ) : (
                      <>
                        <button type="button" disabled={stale} onClick={() => apply(view)}
                          className={`block w-full cursor-pointer border-0 bg-transparent p-0 text-left font-sans text-sm ${stale ? 'cursor-default text-sf-ink-dim' : 'text-sf-ink hover:underline'}`}>
                          {view.name}
                        </button>
                        <p className="m-0 text-xs text-sf-ink-dim">{view.is_shared ? 'Shared' : 'Private'} · {view.owner.name}</p>
                        {stale && <p className="m-0 text-xs text-sf-amber-text">Saved by an older version of this screen, so it can't be applied.</p>}
                        {view.can_edit && (
                          <div className="mt-1 flex flex-wrap gap-3">
                            <button type="button" className={BTN_LINK} disabled={busy} onClick={() => void overwrite(view)}>Update to current</button>
                            <button type="button" className={BTN_LINK} disabled={busy} onClick={() => { setForm({ kind: 'rename', view }); setFormError(null); }}>Rename</button>
                            <button type="button" className={BTN_LINK} disabled={busy}
                              onClick={() => void run(() => postJson(`${VIEWS}/${view.id}/share`, { is_shared: !view.is_shared }),
                                view.is_shared ? 'View is private again.' : 'View shared with the team.', "Couldn't change sharing.", false)}>
                              {view.is_shared ? 'Unshare' : 'Share'}
                            </button>
                            <button type="button" className={BTN_LINK} disabled={busy} onClick={() => void remove(view)}>Delete</button>
                          </div>
                        )}
                      </>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function NameForm({ initial, submit, busy, error, onSubmit, onCancel }: {
  initial: string;
  submit: string;
  busy: boolean;
  error: string | null;
  onSubmit: (name: string) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(initial);
  return (
    <form className="flex flex-col gap-2" onSubmit={e => { e.preventDefault(); if (name.trim()) onSubmit(name.trim()); }}>
      <input aria-label="View name" autoFocus required maxLength={80} placeholder="Name this view" value={name}
        onChange={e => setName(e.target.value)} className={INPUT} />
      {error && <p role="alert" className="m-0 text-xs text-sf-red-text">{error}</p>}
      <div className="flex gap-3">
        <button type="submit" className={BTN_LINK} disabled={busy || !name.trim()}>{submit}</button>
        <button type="button" className={BTN_LINK} onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}

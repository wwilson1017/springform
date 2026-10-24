// Blur/field-commit auto-save (#2032) — the platform's Odoo/Google-Docs save model, so no
// surface has to hand-roll a fifth copy of "commit this field when it loses focus".
//
// THE CONTRACT. A field commits when it loses focus or a discrete value is picked; never on
// a keystroke and never on a timer. `useAutoSave` owns the lifecycle — single-flight with one
// trailing coalesced run, `flush()` that resolves only when the whole chain settles, and a
// thrown `ApiError` 409 classified as `conflict` (the platform's one conflict idiom). The
// CALLER owns the data: its draft, its baseline, its diff, its optimistic-concurrency token,
// and whatever UI a conflict deserves. That is why the hook is adoptable — it never learns a
// record shape. `SaveStatus` renders the ambient line and is the surface's one `aria-live`.
//
// SCOPE. Record-editing surfaces with a loaded baseline. It is NOT a keystroke debouncer
// (`core/hooks/useDebounce` is the one of those) and it does not manage drafts for
// create-forms, which have no baseline to diff against.
//
// Projects' task detail panel is the first consumer; the hand-rolled blur-commits in
// `apps/admin/DevicesPanel`, `apps/staffing/CoveragePanel` + `DishCountsPanel`,
// `apps/morning-meeting/ManageView` and `shared/agent/ConversationSidebar` are the
// duplication it exists to end.
export { useAutoSave } from './useAutoSave';
export { SaveStatus } from './SaveStatus';
// `AutoSave` and `SaveStatusProps` stay internal: no consumer annotates with either, and an
// export nobody imports reads as proven API (#1059). Promote them when one does.
export type { AutoSaveStatus, SaveOutcome } from './types';

/**
 * Where a record-editing surface sits in the auto-save cycle.
 *
 * `idle` ("nothing has happened on this record yet") and `saved` ("your edit landed") are
 * distinct STATES but deliberately share one message — a freshly loaded record genuinely has
 * all changes saved, and Google Docs says so on open too. They stay separate because the
 * machine needs them to: only `dirty` may settle back to `saved`, and `reset()` must be able
 * to return a surface to a state that is not claiming credit for a save it never made.
 */
export type AutoSaveStatus = 'idle' | 'dirty' | 'saving' | 'saved' | 'conflict' | 'error';

/**
 * What one `performSave` attempt achieved. `nothing-to-save` is a success, not a failure:
 * a blur with no actual change must settle the status without issuing a write.
 */
export type SaveOutcome = 'saved' | 'nothing-to-save';

export interface AutoSave {
  status: AutoSaveStatus;
  /** The failure behind `conflict` / `error`; `null` in every other state. */
  errorMessage: string | null;
  /**
   * A field committed (blur, or a discrete pick). Coalesced: at most one save in
   * flight and at most one trailing re-run, whose payload is recomputed at send
   * time. Refused while `conflict` — the user must resolve it first.
   */
  commit: () => void;
  /**
   * Commit and wait. Resolves when the whole chain — including any trailing run —
   * settles: `true` if it landed clean (saved, or nothing to save), `false` on
   * conflict/error. This is what a Save button and a close guard both await.
   */
  flush: () => Promise<boolean>;
  /**
   * The draft changed. Re-derives `dirty` / `saved` from `isDirty()`. Call it from
   * the ONE place the caller mutates its draft; it never issues a write.
   */
  syncDirty: () => void;
  /**
   * Back to `idle`, error cleared, any in-flight chain abandoned. Call it when the
   * record under the form changes, or after the user resolves a conflict.
   */
  reset: () => void;
}

export interface SaveStatusProps {
  status: AutoSaveStatus;
  errorMessage?: string | null;
  /** Extra classes for the caller's layout; the status colour is owned here. */
  className?: string;
}

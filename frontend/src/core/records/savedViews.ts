/**
 * Saved-view payloads. The server's `version` is an edit counter (a PATCH must send the current
 * one); the SCREEN's schema version lives inside the payload, `{schema_version, value}`.
 *
 * Reworked from CakeCRM's `isStaleView`, which compared the server row's version with the
 * surface's: here a view saved under another schema version of the screen is refused, because a
 * renamed or repurposed filter key would silently mean something else. It is shown disabled with
 * the reason, never hidden, so its owner can still overwrite or delete it.
 */
import type { SavedView } from './types';

export function viewPayload(value: unknown, schemaVersion: number): Record<string, unknown> {
  return { schema_version: schemaVersion, value };
}

/** True when the view was saved by another schema version of this screen (or by something else). */
export function isStaleView(view: Pick<SavedView, 'payload'>, schemaVersion: number): boolean {
  return view.payload?.schema_version !== schemaVersion || !('value' in view.payload);
}

/** The view's saved value, or null when it is stale and must not be applied. */
export function viewValue<T>(view: Pick<SavedView, 'payload'>, schemaVersion: number): T | null {
  return isStaleView(view, schemaVersion) ? null : (view.payload.value as T);
}

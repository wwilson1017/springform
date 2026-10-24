/**
 * "This record changed" between record services on one page: CustomFields announces a save and
 * the record's Timeline refetches, so the field-change entry shows without a reload. Module
 * state, no store: listeners come and go with the components.
 */
type Listener = (entityType: string, entityId: number) => void;

const listeners = new Set<Listener>();

/** Subscribe; returns the unsubscribe (an effect's cleanup). */
export function onRecordChanged(listener: Listener): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export function recordChanged(entityType: string, entityId: number): void {
  listeners.forEach(l => l(entityType, entityId));
}

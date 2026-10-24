// Todo GTD — previous / next project for the detail page's arrows.
import type { TodoProject } from './types';

/**
 * The neighbours of `currentId` among the projects sharing its status, in list
 * order (the order the Projects page shows), wrapping at both ends. Null when the
 * project is unknown or is the only one of its status — nothing to cycle to.
 */
export function projectNeighbours(
  projects: Pick<TodoProject, 'id' | 'status'>[], currentId: number,
): { prev: number; next: number } | null {
  const status = projects.find(p => p.id === currentId)?.status;
  const ids = projects.filter(p => p.status === status).map(p => p.id);
  const i = ids.indexOf(currentId);
  if (i < 0 || ids.length < 2) return null;
  return { prev: ids[(i - 1 + ids.length) % ids.length], next: ids[(i + 1) % ids.length] };
}

/** True when a key press belongs to a field the user is typing in. */
export function isTypingTarget(el: EventTarget | null): boolean {
  return el instanceof HTMLElement
    && (el.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName));
}

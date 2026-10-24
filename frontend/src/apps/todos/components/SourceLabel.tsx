import type { Todo } from '../types';

/**
 * Provenance for an item Whisk or an AI tool (an MCP link) created. Nothing for items a person
 * added. A plain <span>, deliberately: TodoRow's whole row is a <button>, and a nested
 * interactive element there is invalid HTML.
 */
export function SourceLabel({ todo }: { todo: Pick<Todo, 'source'> }) {
  if (todo.source !== 'agent') return null;
  return (
    <span
      className="rounded-full border border-sf-line-strong px-2 py-0.5 text-sf-ink-dim"
      title="Added by an AI tool"
    >
      <span aria-hidden="true">✦ </span>
      <span className="sr-only">Added by </span>
      AI
    </span>
  );
}

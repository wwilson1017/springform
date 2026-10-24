import { Link } from 'react-router';
import { todoPath } from '../menu';
import type { TodoProject } from '../types';

interface Props {
  project: TodoProject;
  /** True only on the `active` tab and only when the project has no next action. */
  stalled: boolean;
  onCloseOut: (e: React.MouseEvent, p: TodoProject) => void;
}

/**
 * One project cell in the Projects grid.
 *
 * Module scope, not declared inside the page: a component defined in another component is a new
 * function identity every render, so React remounts the subtree.
 *
 * **A stretched link, not a wrapping one.** An `<a>` may not contain interactive content, and
 * nesting the complete button inside the link makes keyboard and screen-reader behavior
 * unreliable. Here the link is an absolutely-positioned overlay covering the card, the text
 * content sits above it with `pointer-events-none` so clicks fall through to the link, and only
 * the button opts back in with `pointer-events-auto`. One card, two honest targets, no nesting.
 */
export function ProjectCard({ project, stalled, onCloseOut }: Props) {
  const closed = project.status === 'completed' || project.status === 'dropped';
  return (
    <div className="relative rounded-xl border border-sf-line bg-sf-card p-4 transition hover:border-sf-accent/50">
      <Link
        to={todoPath(`/projects/${project.id}`)}
        className="absolute inset-0 rounded-xl focus-visible:ring-2 focus-visible:ring-sf-accent"
      >
        <span className="sr-only">Open project {project.name}</span>
      </Link>
      {/* `flex-wrap` so in a narrow cell the badge and button drop under the title
          instead of crushing it. */}
      <div className="pointer-events-none relative flex flex-wrap items-start justify-between gap-2">
        <p className="min-w-0 break-words font-display font-semibold text-sf-ink">
          {project.name}
        </p>
        <div className="flex max-w-full flex-wrap items-center gap-2">
          {project.visibility === 'team' && (
            <span className="rounded-full bg-sf-ai/15 px-2 py-0.5 text-xs text-sf-ai-text">Team</span>
          )}
          <span className="rounded-full bg-sf-bg px-2 py-0.5 text-xs text-sf-ink-dim">
            {project.open_count} open
          </span>
          <button
            type="button"
            onClick={e => onCloseOut(e, project)}
            title={closed ? 'Reopen this project' : 'Mark this project completed'}
            className="pointer-events-auto rounded-lg border border-sf-line-strong px-2 py-0.5 text-xs font-display text-sf-ink-dim hover:bg-sf-hover hover:text-sf-ink"
          >
            {closed ? 'Reactivate' : '✓ Complete'}
          </button>
        </div>
      </div>
      {project.notes && (
        <p className="pointer-events-none relative mt-1 line-clamp-2 text-sm text-sf-ink-dim">
          {project.notes}
        </p>
      )}
      {stalled && (
        <p className="pointer-events-none relative mt-2 text-xs font-semibold text-sf-accent-text">
          No next action — stalled?
        </p>
      )}
    </div>
  );
}

import { STATUS_META } from '../constants';
import type { Todo } from '../types';
import { useListTz } from '../useTodoMeta';
import { dueLabel, todayStr } from '../util';
import { TeamChip } from './Sharing';
import { SourceLabel } from './SourceLabel';

interface Props {
  todo: Todo;
  onToggleDone: (todo: Todo) => void;
  onToggleStar: (todo: Todo) => void;
  onEdit: (todo: Todo) => void;
  /** Show the status chip (used on Search, where statuses mix). */
  showStatus?: boolean;
}

export function TodoRow({ todo, onToggleDone, onToggleStar, onEdit, showStatus }: Props) {
  const tz = useListTz();
  const finished = todo.status === 'done' || todo.status === 'dropped';
  const today = todayStr(new Date(), tz);
  const due = todo.due_date ? dueLabel(todo.due_date, today) : null;
  const people = todo.people ?? [];
  // A revisit date only matters while the item is open; once its day arrives the
  // chip says so, and before then it shows when the item is coming back.
  const revisit = !finished && todo.revisit_on ? todo.revisit_on : null;

  return (
    <div className="flex items-start gap-3 rounded-xl border border-sf-line bg-sf-card px-3 py-2.5 hover:border-sf-accent/40 transition-colors">
      <input
        type="checkbox"
        checked={todo.status === 'done'}
        onChange={() => onToggleDone(todo)}
        className="mt-1 h-5 w-5 shrink-0 accent-sf-green cursor-pointer"
        aria-label={todo.status === 'done' ? 'Mark not done' : 'Mark done'}
      />
      <button
        type="button"
        onClick={() => onEdit(todo)}
        className="min-w-0 flex-1 text-left"
      >
        {/* A todo you can only half-read is a todo you have to open to triage,
            so the title wraps to as many lines as it needs. `break-words`
            covers the pasted-URL case, which has no break opportunity to wrap
            at and would otherwise push the row's meta chips off screen. */}
        <p className={`text-sm break-words text-sf-ink ${finished ? 'line-through text-sf-ink-dim' : ''}`}>
          {todo.title}
          {todo.repeat && (
            <span
              role="img"
              className="ml-1 text-sf-ai-text "
              title="Recurring"
              aria-label="Recurring"
            >
              ↻
            </span>
          )}
        </p>
        {(todo.context || todo.project_name || todo.source === 'agent' || todo.tags.length > 0
          || people.length > 0 || revisit || due || showStatus || todo.visibility === 'team') && (
          <p className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs">
            {showStatus && (
              <span className={`rounded-full px-2 py-0.5 ${STATUS_META[todo.status].chip}`}>
                {STATUS_META[todo.status].label}
              </span>
            )}
            {due && (
              <span className={due.overdue && !finished
                ? 'font-bold text-sf-accent-text'
                : 'text-sf-ink-dim'}>
                {due.text}
              </span>
            )}
            {revisit && (revisit <= today ? (
              <span className={`rounded-full px-2 py-0.5 ${STATUS_META.someday_maybe.chip}`}
                    title="Its bring-back date has arrived">
                revisit
              </span>
            ) : (
              <span className="text-sf-ink-dim">back {dueLabel(revisit, today).text}</span>
            ))}
            {todo.context && (
              <span className="rounded-full bg-sf-bg px-2 py-0.5 text-sf-ink-dim">{todo.context}</span>
            )}
            {people.map(person => (
              <span key={person} data-person
                    className={`rounded-full px-2 py-0.5 ${STATUS_META.delegated.chip}`}>
                {person}
              </span>
            ))}
            {todo.project_name && (
              <span className="rounded-full bg-sf-bg px-2 py-0.5 text-sf-ink-dim">
                {todo.project_name}
              </span>
            )}
            <TeamChip visibility={todo.visibility} ownerName={todo.owner_name} assigneeName={todo.assignee_name} />
            <SourceLabel todo={todo} />
            {todo.tags.slice(0, 3).map(tag => (
              <span key={tag} className="rounded-full bg-sf-bg px-2 py-0.5 text-sf-ink-dim">
                #{tag}
              </span>
            ))}
          </p>
        )}
      </button>
      <button
        type="button"
        onClick={() => onToggleStar(todo)}
        className={`mt-0.5 shrink-0 text-lg leading-none ${
          todo.star ? 'text-sf-amber' : 'text-sf-line-strong hover:text-sf-amber'
        }`}
        aria-label={todo.star ? 'Unstar' : 'Star as today priority'}
      >
        ★
      </button>
    </div>
  );
}

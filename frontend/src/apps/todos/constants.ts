// Todos: status metadata for chips and grouping.
import type { Todo, TodoStatus, TodoProjectStatus } from './types';

/** Where a todo came from, in words. */
export const SOURCE_LABEL: Record<Todo['source'], string> = { ui: 'web', agent: 'AI', app: 'another app' };

export const STATUS_META: Record<TodoStatus, { label: string; chip: string }> = {
  inbox: { label: 'Inbox', chip: 'bg-sf-bg text-sf-ink-dim' },
  next_action: { label: 'Next', chip: 'bg-sf-green/15  text-sf-green-text ' },
  waiting_for: { label: 'Waiting', chip: 'bg-sf-amber/15  text-sf-amber-text ' },
  delegated: { label: 'Delegated', chip: 'bg-sf-ai/15  text-sf-ai-text ' },
  someday_maybe: { label: 'Someday', chip: 'bg-sf-accent-soft  text-sf-accent-text ' },
  done: { label: 'Done', chip: 'bg-sf-bg text-sf-ink-dim' },
  dropped: { label: 'Dropped', chip: 'bg-sf-bg text-sf-ink-dim line-through' },
};

export const TODO_STATUS_ORDER: TodoStatus[] = [
  'inbox', 'next_action', 'waiting_for', 'delegated', 'someday_maybe', 'done', 'dropped',
];

export const PROJECT_STATUSES: TodoProjectStatus[] = [
  'active', 'someday', 'completed', 'dropped',
];

export const REPEAT_OPTIONS: { value: string; label: string }[] = [
  { value: '', label: 'No repeat' },
  { value: 'daily', label: 'Daily' },
  { value: 'weekdays', label: 'Weekdays' },
  { value: 'weekly', label: 'Weekly' },
  { value: 'monthly', label: 'Monthly' },
  { value: 'yearly', label: 'Yearly' },
];

/** The fields that turn a project name into something you can steer by. */
export interface ProjectFieldValues {
  area_id: number | null;
  purpose: string;
  outcome: string;
}

export const EMPTY_PROJECT_FIELDS: ProjectFieldValues = { area_id: null, purpose: '', outcome: '' };

// Days a next/waiting/delegated item can sit untouched before the Review page
// calls it stale.
export const STALE_DAYS = 14;

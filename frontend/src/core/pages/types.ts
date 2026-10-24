/** Shapes of the Guide, Requests, Change log and Jobs routes (they return untyped dicts, so
 * `types.gen.ts` has nothing to offer here). */
import type { UserRef } from '../api/types';

export interface GuideTopic {
  slug: string;
  title: string;
  summary: string;
  /** "core" (or null) for Springform's own topics, else the owning app's slug. */
  app: string | null;
}

export interface GuideHit {
  slug: string;
  title: string;
  snippet: string;
  app: string | null;
}

export interface GuideTopicBody extends GuideTopic {
  body_markdown: string;
}

export interface RequestsConfig {
  configured: boolean;
  warning_text: string;
  repo: string | null;
}

export type RequestState = 'open' | 'closed';

export interface RequestRow {
  id: number;
  issue_number: number | null;
  url: string | null;
  state: RequestState;
  title: string;
  app: string;
  description: string;
  labels: string[];
  requested_by: UserRef | null;
  created_at: string;
  updated_at: string;
}

export interface ChangeRow {
  id: number;
  at: string;
  user: UserRef | null;
  app: string;
  entity_type: string;
  entity_id: number;
  /** Null when the record is gone (or its type is no longer installed). */
  title: string | null;
  url: string | null;
  field: string;
  old: unknown;
  new: unknown;
  reason: string | null;
  deleted_at: string | null;
}

export type RunStatus = 'running' | 'ok' | 'error' | 'timed_out' | 'interrupted' | 'skipped';

export interface JobInfo {
  name: string;
  app: string;
  /** Seconds between runs, or null for a daily `at` job. */
  every: number | null;
  /** "HH:MM" in the install timezone, or null for an `every` job. */
  at: string | null;
  timeout: number;
  last_run: { status: RunStatus; started_at: string | null; finished_at: string | null; error: string | null } | null;
  in_flight: boolean;
}

export interface JobRun {
  id: number;
  job: string;
  app: string;
  trigger: 'schedule' | 'manual' | 'nudge';
  status: RunStatus;
  scheduled_for: string | null;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
}

export interface DeadOutboxRow {
  id: number;
  hook: string;
  attempts: number;
  last_error: string | null;
  created_at: string;
  dead_at: string;
}

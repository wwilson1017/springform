/** Shapes of the Guide, Requests, Change log and Jobs routes, from the generated schemas. */
import type { components } from '../api/types.gen';

type S = components['schemas'];

/** `app` is "core" for Springform's own topics, else the owning app's slug. */
export type GuideTopic = S['GuideTopic'];
export type GuideHit = S['GuideHit'];
export type GuideTopicBody = S['GuideTopicBody'];
export type RequestsConfig = S['RequestsConfig'];
export type RequestRow = S['RequestRow'];
export type RequestState = RequestRow['state'];
/** `title` and `url` are null when the record is gone (or its type is no longer installed). */
export type ChangeRow = S['ChangeRow'];
/** `every` is seconds between runs (null for a daily job); `at` is "HH:MM" in the install timezone. */
export type JobInfo = S['JobInfo'];
export type JobRun = S['JobRun'];
export type RunStatus = JobRun['status'];
export type DeadOutboxRow = S['DeadOutboxRow'];
/** POST /api/core/requests/refresh */
export type Updated = S['Updated'];

/**
 * The CRM's API at /api/crm. Response shapes come from the generated OpenAPI types (the router
 * declares a response model on every route); request bodies are the same models' inputs.
 */
import { del, fetchJson, patchJson, postJson, putJson, upload } from '../../core/api/client';
import type { components } from '../../core/api/types.gen';

type S = components['schemas'];
export type Deal = S['Deal'];
export type DealDetail = S['DealDetail'];
export type DealIn = S['DealIn'];
export type DealPatch = S['DealPatch'];
export type Board = S['Board'];
export type StageSummary = S['StageSummary'];
export type StageEvent = S['StageEvent'];
export type Activity = S['Activity'];
export type BulkMoveOut = S['BulkMoveOut'];
export type Dashboard = S['Dashboard'];
export type Today = S['Today'];
export type TodayItem = S['TodayItem'];
export type WeeklyTouches = S['WeeklyTouches'];
export type WeeklyTouchDetail = S['WeeklyTouchDetail'];
export type TouchedDeal = S['TouchedDeal'];
export type Analytics = S['Analytics'];
export type PipelineAnalytics = S['PipelineAnalytics'];
export type StaleDeals = S['StaleDeals'];
export type DealHealth = S['DealHealth'];
export type TouchEvidence = S['TouchEvidence'];
export type StageCriteria = S['StageCriteria'];
export type ImportPerson = S['ImportPerson'];
export type ImportParsed = S['ImportParsed'];
export type ImportResult = S['ImportResult'];
export type CrmSettings = S['CrmSettings'];
export type Stage = Deal['stage'];

/** The timeline, attachments and custom-fields entity type of a deal. */
export const DEAL_ENTITY = 'crm.deal';

const BASE = '/api/crm';
const qs = (params: Record<string, string | number | boolean | null | undefined>) => {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== '') q.set(k, String(v));
  const s = q.toString();
  return s ? `?${s}` : '';
};

// ── Deals ───────────────────────────────────────────────────────────────────

/** The whole board in one page; a big install bounds it with `limit_per_stage`. */
export const boardUrl = (includeArchived: boolean) =>
  `${BASE}/deals${qs({ include_archived: includeArchived || undefined, limit_per_stage: 200 })}`;
export const searchUrl = (q: string, includeArchived: boolean) =>
  `${BASE}/deals/search${qs({ q, include_archived: includeArchived || undefined, limit: 100 })}`;
export const dealUrl = (id: number | string) => `${BASE}/deals/${id}`;
export const recordDealsUrl = (entityType: string, id: number) =>
  `${BASE}/${entityType === 'core.organization' ? 'organizations' : 'people'}/${id}/deals`;

/** The generated DealIn marks defaulted fields required; the server fills them. */
export const createDeal = (body: Partial<DealIn> & Pick<DealIn, 'title'>) => postJson<Deal>(`${BASE}/deals`, body);
export const updateDeal = (id: number, body: DealPatch) => patchJson<Deal>(dealUrl(id), body);
export const bulkMove = (ids: number[], stage: Stage, closedOn?: string) =>
  postJson<BulkMoveOut>(`${BASE}/deals/bulk-move`, { ids, stage, ...(closedOn ? { closed_on: closedOn } : {}) });
export const markWon = (id: number, closedOn?: string) => postJson<Deal>(`${dealUrl(id)}/won`, closedOn ? { closed_on: closedOn } : {});
export const markLost = (id: number, reason: string) => postJson<Deal>(`${dealUrl(id)}/lost`, { reason });
export const archiveDeal = (id: number, reason: string) => postJson<Deal>(`${dealUrl(id)}/archive`, { reason });
export const restoreDeal = (id: number) => postJson<Deal>(`${dealUrl(id)}/restore`);
export const mergeDeal = (targetId: number, sourceId: number) => postJson<Deal>(`${dealUrl(targetId)}/merge`, { source_id: sourceId });
export const searchDeals = (q: string) => fetchJson<Deal[]>(searchUrl(q, false));

// ── Activity ────────────────────────────────────────────────────────────────

export const logActivity = (body: { activity: string; note: string; deal_id?: number; person_id?: number | null }) =>
  postJson<Activity>(`${BASE}/activity`, body);
export const updateActivity = (id: number, body: { activity?: string; note?: string }) =>
  patchJson<Activity>(`${BASE}/activity/${id}`, body);
export const deleteActivity = (id: number) => del(`${BASE}/activity/${id}`);

// ── Dashboard, Today, touches, analytics ────────────────────────────────────

export const dashboardUrl = `${BASE}/dashboard`;
export const todayUrl = `${BASE}/dashboard/today`;
export const touchesUrl = (start?: string, end?: string) => `${BASE}/dashboard/weekly-touches${qs({ start, end })}`;
export const touchDetailUrl = (owner: string, start?: string, end?: string) =>
  `${BASE}/dashboard/weekly-touches/detail${qs({ owner, start, end })}`;
export const analyticsUrl = (days: number) => `${BASE}/analytics${qs({ days })}`;
export const pipelineAnalyticsUrl = (days: number) => `${BASE}/analytics/pipeline${qs({ days })}`;
export const staleUrl = (days?: number) => `${BASE}/stale-deals${qs({ days, limit: 200 })}`;

// ── Stage criteria, import, settings ────────────────────────────────────────

export const stageCriteriaUrl = `${BASE}/stage-criteria`;

export const saveStageCriteria = (stage: Stage, body: { summary: string; checklist: string[] }) =>
  putJson<StageCriteria>(`${stageCriteriaUrl}/${stage}`, body);

/** The DELETE answers the standard criteria, but core's `del` drops bodies, so read them back. */
export async function resetStageCriteria(stage: Stage): Promise<StageCriteria> {
  await del(`${stageCriteriaUrl}/${stage}`);
  return (await fetchJson<StageCriteria[]>(stageCriteriaUrl)).find(c => c.stage === stage)!;
}

export function parseImport(file: File) {
  const form = new FormData();
  form.append('file', file);
  return upload<ImportParsed>(`${BASE}/import/parse`, form);
}
export const confirmImport = (people: ImportPerson[]) => postJson<ImportResult>(`${BASE}/import/confirm`, { people });

export const settingsUrl = `${BASE}/settings`;
export const saveSettings = (body: Partial<CrmSettings>) => patchJson<CrmSettings>(settingsUrl, body);
export const resetCrm = () => postJson<{ deals: number; activity: number }>(`${BASE}/reset`, { confirm: 'RESET' });

/** Active users, for the owner picker. Any member may read it (the mention list). */
// simplification: at most 20 users (the mention route's cap), upgrade path: a paged core users directory.
export const usersUrl = '/api/core/timeline/mentionable';

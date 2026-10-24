/** GET /api/core/sheets/credentials. The key itself is never returned. */
export interface SheetCredentials {
  configured: boolean;
  service_account_email: string | null;
}

export type SheetSchedule = 'hourly' | 'daily' | 'manual';

/** One connected sheet, declared by an app's manifest and configured by an admin. */
export interface Sheet {
  id: number;
  app: string;
  name: string;
  description: string;
  spreadsheet_id: string;
  range: string;
  mode: 'read' | 'write';
  schedule: SheetSchedule;
  enabled: boolean;
  last_synced_at: string | null;
  last_error: string | null;
  row_count: number | null;
  created_at: string;
  updated_at: string;
  fetched_at: string | null;
  /** Both spreadsheet_id and range are set. */
  configured: boolean;
}

/** GET /api/core/sheets/{id}/preview: the cached header and first 20 rows. */
export interface SheetPreview {
  header: string[];
  rows: string[][];
  fetched_at: string | null;
  row_count: number | null;
  stale: boolean;
}

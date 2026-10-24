/** One recovery set on disk: `<stamp>.sqlite` plus `<stamp>.manifest.json`. */
export interface BackupSet {
  /** `YYYYMMDDTHHMMSSZ`, UTC. */
  stamp: string;
  created_at: string | null;
  snapshot_bytes: number | null;
  blob_count: number | null;
  /** From the run log; null for a set no run on this install recorded. */
  status: string | null;
  /** The manifest parses and its snapshot is present at the recorded size. */
  manifest_ok: boolean;
}

/** A `core_backups` row: one run of the job or of "Back up now". */
export interface BackupRun {
  id: number;
  started_at: string;
  finished_at: string;
  status: 'ok' | 'error' | 'skipped';
  snapshot: string | null;
  manifest: string | null;
  byte_size: number | null;
  sha256: string | null;
  /** Why it failed, or why it was skipped (low disk space). */
  error: string | null;
}

export type KeySource = 'env' | 'file';

/** GET /api/core/backups */
export interface BackupsOverview {
  sets: BackupSet[];
  last_backup_at: string | null;
  last_run: BackupRun | null;
  key_source: KeySource;
  key_shown: boolean;
}

/** POST /api/core/backups/key: the key once (file), or only its fingerprint (env). 410 once shown. */
export type KeyReveal = { key_source: 'file'; key: string; fingerprint: string } | { key_source: 'env'; fingerprint: string };

import type { components } from '../api/types.gen';

type S = components['schemas'];

/** One recovery set on disk: `<stamp>.sqlite` plus `<stamp>.manifest.json`. `status` is null for a set no run on this install recorded. */
export type BackupSet = S['BackupSet'];
/** A `core_backups` row: one run of the job or of "Back up now". */
export type BackupRun = S['BackupRun'];
/** POST /api/core/backups/run: the recorded row, or the bare outcome when it could not be recorded. */
export type BackupRunResult = BackupRun | S['BackupRunUnrecorded'];
export type KeySource = BackupsOverview['key_source'];
/** GET /api/core/backups. `key_mismatch` is the newest manifest whose key fingerprint differs from this install's. */
// simplification: typed by hand until the backend's overview model declares key_mismatch; then the bare schema.
export type BackupsOverview = S['BackupsOverview'] & { key_mismatch?: string | null };
/** POST /api/core/backups/key: `key` once (file source), only the fingerprint (env). 410 once shown. */
export type KeyReveal = S['KeyReveal'];

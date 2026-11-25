import type { components } from '../api/types.gen';

type S = components['schemas'];

/** One recovery set on disk: `<stamp>.sqlite` plus `<stamp>.manifest.json`. `status` is null for a set no run on this install recorded. */
export type BackupSet = S['BackupSet'];
/** A `core_backups` row: one run of the job or of "Back up now". */
export type BackupRun = S['BackupRun'];
/** POST /api/core/backups/run: the recorded row, or the bare outcome when it could not be recorded. */
export type BackupRunResult = BackupRun | S['BackupRunUnrecorded'];
export type KeySource = BackupsOverview['key_source'];
/** GET /api/core/backups. `key_mismatch` names the newest manifest taken with another encryption key. */
export type BackupsOverview = S['BackupsOverview'];
/** POST /api/core/backups/key: `key` once (file source), only the fingerprint (env). 410 once shown. */
export type KeyReveal = S['KeyReveal'];
/** The off-site copy: the destination minus its secret, `encrypted` (a passphrase is set), the last upload, `stale` (> 48 h). */
export type Offsite = S['Offsite'];
/** PUT /api/core/backups/destination. `secret_key` is write-only: leave it out to keep the stored one. */
export type DestinationBody = S['DestinationIn'];
/** Fired on window after a backup or an off-site change, so the admin banner re-reads the state. */
export const BACKUPS_CHANGED = 'sf:backups-changed';

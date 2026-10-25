import type { components } from '../api/types.gen';

type S = components['schemas'];

/** GET /api/core/sheets/credentials. The key itself is never returned. */
export type SheetCredentials = S['SheetCredentials'];
/** One connected sheet, declared by an app's manifest and configured by an admin. */
export type Sheet = S['ConnectedSheet'];
export type SheetSchedule = Sheet['schedule'];
/** GET /api/core/sheets/{id}/preview: the cached header and first 20 rows. */
export type SheetPreview = S['SheetPreview'];

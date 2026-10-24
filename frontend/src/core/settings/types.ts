import type { components } from '../api/types.gen';

type S = components['schemas'];

/** GET /api/core/workspace (any signed-in user). */
export type Workspace = S['Workspace'];

/** GET/PUT /api/core/settings (admin). Secret values are never returned; `secrets` says whether one is set. */
export type CoreSettings = S['CoreSettings'];

export const SETTINGS_URL = '/api/core/settings';

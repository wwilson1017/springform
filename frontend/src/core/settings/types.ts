/** GET /api/core/workspace (any signed-in user). */
export interface Workspace {
  name: string;
  timezone: string;
  version: string;
  preview: boolean;
}

/** GET/PUT /api/core/settings (admin). Secret values are never returned; `secrets` says whether one is set. */
export interface CoreSettings {
  values: Record<string, unknown>;
  secrets: Record<string, boolean>;
  defaults: Record<string, unknown>;
}

export const SETTINGS_URL = '/api/core/settings';

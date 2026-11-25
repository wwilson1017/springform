import type { Offsite } from './types';

/** An `offsite` block for tests: not configured unless `extra` says so. */
export const offsite = (extra: Partial<Offsite> = {}): Offsite => ({
  configured: false,
  unreadable: false,
  endpoint: null,
  bucket: null,
  region: null,
  prefix: null,
  access_key_id: null,
  retention: null,
  encrypted: false,
  last_success_at: null,
  last_success_bytes: null,
  last_error: null,
  stale: false,
  ...extra,
});

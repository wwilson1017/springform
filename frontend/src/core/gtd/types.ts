import type { components } from '../api/types.gen';

/** GET /api/core/gtd and every GTD route's answer: the address, the connected server, a connect waiting. */
export type GtdState = components['schemas']['GtdState'];

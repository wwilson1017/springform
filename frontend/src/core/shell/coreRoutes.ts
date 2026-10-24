import type { ReactNode } from 'react';

/**
 * Core areas add pages the way they add nav and Settings cards: `src/core/<area>/routes.tsx`
 * default-exports `CoreRoute[]`. Shell routes render inside the signed-in Layout (admin ones
 * behind RequireAdmin); public ones (an invite or reset link) render beside /login. The module is
 * eager, so a heavy page is `lazy()` there and the module holds only route data. Nobody edits
 * Root.tsx to add a page. Paths are relative to the root, without a leading slash
 * (`people/:id`, `guide/*`), and the first segment must be one of the backend's reserved slugs.
 */
export interface CoreRoute {
  path: string;
  element: ReactNode;
  /** Rendered outside the signed-in shell, like /login. */
  public?: boolean;
  /** Members get the Not allowed page. */
  admin?: boolean;
}

const ROUTES: CoreRoute[] = Object.values(
  import.meta.glob<CoreRoute[]>('../*/routes.tsx', { eager: true, import: 'default' }),
).flat();

export const coreRoutes = (where: 'public' | 'shell'): CoreRoute[] =>
  ROUTES.filter(r => (where === 'public') === Boolean(r.public));

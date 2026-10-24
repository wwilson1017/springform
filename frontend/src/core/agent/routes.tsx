import { lazy } from 'react';
import type { CoreRoute } from '../shell/coreRoutes';

/** The chat (and its markdown renderer) loads on the first visit to /whisk, never at boot. */
function whisk() {
  const Page = lazy(() => import('./WhiskPage'));
  return <Page />;
}

// One splat route, `/whisk` and `/whisk/<conversation id>`: a new chat moves to its id's URL
// mid-stream, and staying on the same route keeps the page (and the stream) mounted.
export default [
  { path: 'whisk/*', element: whisk() },
] satisfies CoreRoute[];

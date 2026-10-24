import { createElement, lazy } from 'react';
import type { CoreRoute } from '../shell/coreRoutes';

// createElement over a named lazy component: a component declared beside a data export trips
// react-refresh/only-export-components.
export default [
  { path: 'backups', element: createElement(lazy(() => import('./BackupsPage'))), admin: true },
] satisfies CoreRoute[];

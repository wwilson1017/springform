/* eslint-disable react-refresh/only-export-components -- a route-data module: lazy pages and a default-exported array */
import { lazy } from 'react';
import type { CoreRoute } from '../shell/coreRoutes';

const InvitePage = lazy(() => import('./InvitePage'));
const ResetPasswordPage = lazy(() => import('./ResetPasswordPage'));

// The links the backend mails or hands to an admin: PUBLIC_URL/invite/<token> and /reset-password/<token>.
export default [
  { path: 'invite/:token', element: <InvitePage />, public: true },
  { path: 'reset-password/:token', element: <ResetPasswordPage />, public: true },
] satisfies CoreRoute[];

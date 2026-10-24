# Provenance

Every file lifted substantially from another repository gets a row here. All donors are the maintainer's own MIT code. "Commit" is the donor commit the file was read at.

| Springform path | Source repo | Commit | Source path | Notes |
|---|---|---|---|---|
| `frontend/package.json` | CakeCRM | 3a71a7d | `frontend/package.json` | Script names and dependency majors; Vite 7 (donor is on 8), jsdom 29 (30 needs Node 22), `react-router` 7 instead of `react-router-dom` 7, fonts dropped. |
| `frontend/tsconfig.json`, `frontend/tsconfig.app.json`, `frontend/tsconfig.node.json`, `frontend/eslint.config.js` | CakeCRM | 3a71a7d | same paths | Standard Vite + typescript-eslint config shape from the donor's seed commit; `tsconfig.node.json` also covers the apps plugin and vitest config. |
| `frontend/vitest.config.ts` | CakeCRM | 3a71a7d | `frontend/vitest.config.ts` | Standalone config, fail-closed guards, non-UTC `TZ` pin, `__INDEX_CSS__` define. Default environment jsdom; donor-specific defines dropped. |
| `frontend/index.html` | CakeCRM | 3a71a7d | `frontend/index.html` | Anti-flash theme script; key renamed `springform_theme`. |
| `frontend/src/index.css` | CakeCRM | 3a71a7d | `frontend/src/index.css` | Tokens renamed `--color-ck-*` → `--color-sf-*`. Ink ramp, accent and status hues kept with their values; stage hues, launcher, collection aliases, highlight.js and bottom-bar rules dropped; system font stacks. |
| `frontend/src/core/theme/useTheme.ts` | CakeCRM | 3a71a7d | `frontend/src/core/theme/useTheme.ts` | Storage key renamed. |
| `frontend/src/core/theme/inkContrast.test.ts`, `hueContrast.test.ts`, `palette.testutil.ts` | CakeCRM | 3a71a7d | `frontend/src/core/theme/inkContrast.test.ts`, `hueContrast.test.ts` | WCAG arithmetic and stylesheet parser shared in one util; surface models cut to the shell's (CRM stage and deal-card stacks dropped). |
| `frontend/src/core/components/BootFallback.tsx` | CakeCRM | 3a71a7d | `frontend/src/core/components/BootFallback.tsx` | Token classes renamed. |
| `frontend/src/core/components/ChunkErrorBoundary.tsx` | CakeCRM | 3a71a7d | `frontend/src/core/components/ChunkErrorBoundary.tsx` | Comments condensed, guard key renamed, product name removed from copy. |
| `frontend/src/core/components/ChunkErrorBoundary.test.tsx` | CakeCRM | 3a71a7d | `frontend/src/core/components/ChunkErrorBoundary.test.tsx` | Two cases kept (reload once; no reload on a render bug or a panel), rewritten on Testing Library. |
| `frontend/src/core/api/client.ts` | CakeCRM | 3a71a7d | `frontend/src/core/api/client.ts` | `ApiError` and the never-settling 401 redirect kept; bearer token replaced by the session cookie; JSON helpers and the openapi-fetch client added. |
| `frontend/src/core/auth/AuthContext.tsx` | CakeCRM | 3a71a7d | `frontend/src/core/auth/AuthContext.tsx` | sessionStorage, BroadcastChannel and 2FA steps dropped; `GET /api/me` with the cookie. |
| `frontend/src/core/auth/guards.tsx` | CakeCRM | 3a71a7d | `frontend/src/core/auth/ProtectedRoute.tsx` | `RequireAuth`; `RequireAdmin` added. |
| `frontend/src/core/auth/LoginPage.tsx`, `AuthLayout.tsx` | CakeCRM | 3a71a7d | `frontend/src/login/LoginPage.tsx` | Password form and classes kept; 2FA step dropped; Google button, preview picker, status note and `not_invited` notice added. |
| `frontend/src/core/settings/settingsSections.ts` | CakeCRM | 3a71a7d | `frontend/src/crm/settingsSections.ts` | Derived-visibility rule kept; fixed CRM sections replaced by discovered core sections plus one section per app. |
| `frontend/src/core/Root.tsx` | CakeCRM | 3a71a7d | `frontend/src/Root.tsx`, `frontend/src/App.tsx` | Boundary, Suspense and host placement; routes are Springform's. |
| `frontend/src/bootSplit.test.ts` | CakeCRM | 3a71a7d | `frontend/src/bootSplitBuild.test.ts` | In-memory build and chunk-graph walk kept; assertions are Springform's (apps lazy, contributions eager and tiny). |
| `frontend/src/shared/toast.ts`, `confirm.ts`, `ConfirmHost.tsx`, `ToastViewport.tsx`, `LoadError.tsx`, `useIsMobile.ts`, `formatDate.ts`, `styles.ts` | CakeCRM | 3a71a7d | `frontend/src/shared/` same names | Token names `sf`; launcher clearance and unused exports dropped. |
| `frontend/src/shared/MobileMenuDrawer.tsx` | CakeCRM | 3a71a7d | `frontend/src/shared/MobileMenuDrawer.tsx` | Generalised: items come from the caller. |
| `frontend/src/shared/icons.tsx` | CakeCRM | 3a71a7d | `frontend/src/shared/icons.tsx` | `Ico` helper and `IconProps` lifted; every glyph redrawn from plain geometry, because several donor glyphs follow an icon set's shapes. |

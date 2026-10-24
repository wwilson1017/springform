# Provenance

Springform is MIT. Some of its code is lifted from the maintainer's other repositories, which the
maintainer wrote alone and may relicense. Every lifted file is recorded here, with the source repository,
the source commit sha and the source path, so its origin can be checked.

**The lift check**, run on the source repository before a file is lifted:

```bash
git log --follow --format=%an -- <source path> | sort -u      # only the maintainer's own identities
grep -nEi 'copyright|@license|source:|stackoverflow' <source path>   # no third-party notices
```

Anything not the maintainer's own is rewritten or dropped. "Lifted" means substantially copied;
code that only follows a donor's general shape is not listed. Rows are kept when branches merge:
resolve conflicts here by keeping every row.

Author identities seen so far, all the maintainer's: the maintainer's name, GitHub account,
and commits made by the maintainer's coding agent under their direction (author `Claude`).

| Springform path | Source repo | Commit | Source path | Notes |
|---|---|---|---|---|
| `backend/core/db.py` (connections, `transaction()`) | todo-gtd | f2f74d8 | `backend/db.py` (lines 499–540, 782–825) | Per-thread connection, pragmas, data-dir write probe, process write lock + `BEGIN IMMEDIATE`. Added: nesting guard, outbox nudge, `flock`, SQLite version/FTS5 assertion. `synchronous=NORMAL` (donor FULL), per the plan. |
| `backend/core/db.py` (migration runner) | CakeCRM | 3a71a7d | `backend/core/postgres.py` (`run_migrations`, lines 181–248) | Shape only: tracking table, ordered files, one transaction per file. Rewritten for SQLite `executescript` with checksums, explicit `ROLLBACK`, the `requires_core` check and the core drop/rename lint. |
| `backend/core/secrets.py` | CakeCRM | 3a71a7d | `backend/core/encryption.py`, `backend/core/secret_store.py` | `enc:v1:` Fernet values and the env → data-dir file → generated ladder. Keychain step, dict helpers and the ephemeral fallback dropped; an invalid env value raises. |
| `backend/core/localtime.py` | CakeCRM | 3a71a7d | `backend/core/localtime.py` | Zone from the `timezone` setting instead of `TIMEZONE`; "now" from `core.clock`. |
| `backend/core/auth/service.py` | CakeCRM | 3a71a7d | `backend/users/service.py`, `backend/core/auth.py` | Email normalization, bcrypt failing closed, the timing equalizer, the `'!'` sentinel, epoch bump. Login limits moved from memory to `core_login_attempts`. |
| `backend/core/auth/jwt.py`, `backend/core/auth/deps.py`, `backend/core/auth/router.py` | CakeCRM | 3a71a7d | `backend/core/auth.py` | `sub` + `pwd_epoch` token, live-row `current_user`, `require_admin`. python-jose → PyJWT; the `sf_session` cookie is read before a bearer header; 2FA and password change are not lifted yet. |
| `backend/core/auth/bootstrap.py` | CakeCRM | 3a71a7d | `backend/users/bootstrap.py` | Structure only (first admin in one locked transaction); env-password seeding and legacy claims replaced by the setup token. |
| `backend/core/timeline/service.py` | CakeCRM | 3a71a7d | `backend/crm/chatter_service.py` | Body validation, bounded windows, author per row; generalised to any registered entity behind `entities.authorize`. Mentions and scoring calls not lifted. |
| `backend/core/agent/registry.py`, `backend/core/agent/spec.py` | CakeCRM | 3a71a7d | `backend/assistant/registry.py`, `backend/assistant/confirm_tier.py` | Fail-loud validation (duplicates, boolean `writes`, `confirm_tier` only `"routine"` and only on writes); dict defs became `ToolSpec`. Sources, read-only mode and dispatch not lifted. |
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
| `AGENTS.md` | CakeCRM | `3a71a7dfa0ea2bb7b38285e5cfaba2b2533fad13` | `AGENTS.md` | Headings and the Tests and CI rules kept; body rewritten for Springform. |
| `CLAUDE.md` | CakeCRM | `3a71a7dfa0ea2bb7b38285e5cfaba2b2533fad13` | `CLAUDE.md` | The `@AGENTS.md` import line only. |
| `docs/AUTO_ISSUES.md` | CakeCRM | `3a71a7dfa0ea2bb7b38285e5cfaba2b2533fad13` | `docs/AUTO_ISSUES.md` | Trimmed: mirror-conventions and AI review sections dropped, label set replaced, merge policy updated. |
| `scripts/seed-labels.sh` | CakeCRM | `3a71a7dfa0ea2bb7b38285e5cfaba2b2533fad13` | `scripts/seed-labels.sh` | Label list replaced; `app:<slug>` labels added from `backend/apps/*/app.json`. |
| `.github/workflows/ci.yml` | CakeCRM | `3a71a7dfa0ea2bb7b38285e5cfaba2b2533fad13` | `.github/workflows/ci.yml` | Structure, action pins and the gitleaks step kept; jobs rewritten for uv, type diff, image test and fork scope. |
| `railway.json` | CakeCRM | `3a71a7dfa0ea2bb7b38285e5cfaba2b2533fad13` | `railway.json` | Same keys; healthcheck `/up`, mount `/data`. |
| `backend/core/files/service.py` (filename normalization, MIME allow-list, retry dedupe) | CakeCRM | 3a71a7d | `backend/crm/attachment_service.py` | `normalize_filename` lifted (255-byte cap, donor 120); the allow-list rule and "the same bytes on the same record return the existing row". Bytes moved from a BYTEA column to content-addressed blobs on the volume; per-note cap, magic-byte sniffing and `FOR UPDATE` locking dropped (one SQLite write lock). |
| `backend/core/files/thumbnails.py` | CakeCRM | 3a71a7d | `backend/core/thumbnails.py` | Source ceilings, JPEG draft decode, EXIF transpose only when tagged, frame cap, process-wide decode semaphore, shrink before flatten. JPEG only (no WebP ladder; `core_files` has no thumbnail mime column), one shrink step, decoders limited to JPEG/PNG/GIF/WebP, Pillow imported eagerly. |
| `backend/core/backup/service.py` | todo-gtd | f2f74d8 | `backend/backup.py` | Shape: temp file then `os.replace`, the free-space floor (database size + 100 MB), prune of leftovers, never-raise wrapper. Rewritten: `VACUUM INTO` instead of the online backup API, recovery sets with a manifest written last (blob list read from the snapshot, key fingerprint), keep the newest 7 sets instead of 24 h + 14 daily, `core_backups` rows, one run at a time. |

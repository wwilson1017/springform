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
| `AGENTS.md` | CakeCRM | `3a71a7dfa0ea2bb7b38285e5cfaba2b2533fad13` | `AGENTS.md` | Headings and the Tests and CI rules kept; body rewritten for Springform. |
| `CLAUDE.md` | CakeCRM | `3a71a7dfa0ea2bb7b38285e5cfaba2b2533fad13` | `CLAUDE.md` | The `@AGENTS.md` import line only. |
| `docs/AUTO_ISSUES.md` | CakeCRM | `3a71a7dfa0ea2bb7b38285e5cfaba2b2533fad13` | `docs/AUTO_ISSUES.md` | Trimmed: mirror-conventions and AI review sections dropped, label set replaced, merge policy updated. |
| `scripts/seed-labels.sh` | CakeCRM | `3a71a7dfa0ea2bb7b38285e5cfaba2b2533fad13` | `scripts/seed-labels.sh` | Label list replaced; `app:<slug>` labels added from `backend/apps/*/app.json`. |
| `.github/workflows/ci.yml` | CakeCRM | `3a71a7dfa0ea2bb7b38285e5cfaba2b2533fad13` | `.github/workflows/ci.yml` | Structure, action pins and the gitleaks step kept; jobs rewritten for uv, type diff, image test and fork scope. |
| `railway.json` | CakeCRM | `3a71a7dfa0ea2bb7b38285e5cfaba2b2533fad13` | `railway.json` | Same keys; healthcheck `/up`, mount `/data`. |

Ten commands are gone, with no alias, and so are the keys and flags only they read. What each did,
and what to use instead:

- `stayfixed assess`, `stayfixed gate` and `stayfixed adopt promote`, the gate ratchet. `stayfixed
  doctor` and the checks themselves (`docs check`, `docs trail --check`, `bugs check`, `plan check`,
  `commit check`) still report each finding, and your own CI runs the ones you choose. The reusable
  workflow `check.yml` went with `gate`: a caller pinned to an earlier commit keeps running that
  commit's workflow, and one pinned to a later commit no longer finds the file, so delete the caller
  workflow (`init` wrote it as `.github/workflows/stayfixed.yml`). Nothing writes
  `.stayfixed/assessment.json` any more; delete it.
- `stayfixed upgrade` and `stayfixed uninstall`. A file `init` wrote is yours to edit by hand. To
  take a repository off stayfixed, delete the files `init` wrote, the `stayfixed:ignore` region of
  `.gitignore` (not the file, unless `init` created it) and `.stayfixed/manifest.json`.
- `stayfixed memory refs` and `stayfixed memory fit`. `stayfixed doctor`'s `bundles` row still says
  whether each bundle fits its slots.
- `stayfixed trust list` and `stayfixed trust revoke`. `stayfixed memory inventory --json` gives
  each note's `reviewed` state and the `unreviewed` total, and `stayfixed doctor`'s `memory` row the
  store's unreviewed count; both only read. A promoted note is withdrawn by editing it, which
  changes its digest, or by deleting it.
- `stayfixed test hygiene`. The red-run note the hook adds after a failed `Bash` call says the same.

Delete these from an existing `stayfixed.toml`, or every command that loads it exits 1 with the
loader's refusal, `[stayfixed] has unknown key(s): enforced` for a key and `has unknown section(s):
gates` for a table. `stayfixed doctor` is the exception: it warns `not-initialised`, says how many
settings it ignored and exits 0, and a session's hooks load the file the same way:

- `[stayfixed] enforced`, and `[stayfixed] state` where the file still has it;
- the whole `[gates]` table, `[gates.custom]` included: `stayfixed bugs regressions --timeout
  SECONDS` now bounds each regression's run, with the default `custom_timeout_seconds` had, 600
  seconds;
- the whole `[ci]` table;
- the whole `[artifacts]` table;
- `[commit_messages] types`; `attribution_check` stays.

`stayfixed bugs check --base` loads the `stayfixed.toml` of the commit a change forked from, so a
base branch whose copy still carries one of these fails it on every pull request: push the edit to
the base branch first.

`stayfixed init` now writes five files, the `.gitignore` region and its manifest: `stayfixed.toml`,
`docs/roadmap.md` with its trail markers, `docs/trail.toml`, the generated bug index
`docs/bug-reports.md`, `docs/bugs/audits/README.md`, and the `stayfixed:ignore` region, which keeps
`.stayfixed/local/` out of git. It writes no `AGENTS.md`, `CLAUDE.md` or workflow, and
`init --json` carries no `skipped` key. Its `--local`, `--commit-type` and `--no-ci` flags are gone,
and `init --questions` no longer asks about CI or commit types. `stayfixed doctor` reports thirteen
rows: the `ci-ref` row went with `[ci]`.

The generated bug index no longer links a runbook, since `init` no longer writes one: run
`stayfixed bugs index` once and commit it, or `bugs index --check` and `bugs check` report the
committed index stale.

An earlier `init` or `[artifacts] local` left files this release neither writes nor reads, and you
may delete each by hand: `.stayfixed/local/artifacts/` and `.stayfixed/local/artifacts.json`; the
profile's rules, `docs/stayfixed/rules/<profile>.md` and `.claude/rules/stayfixed-<profile>.md`;
`docs/roadmap-history.md`; `docs/runbooks/bug-reports.md`; and the `.stayfixed/assessment.json`
line in the `stayfixed:ignore` region. `.stayfixed/manifest.json` keeps its records of the artifacts
this release no longer writes, and nothing reads them.

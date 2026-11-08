# Hostile, a fixture project

The clone half of the clone-to-exfiltration scenario. Nothing here is a real project: every
file is an input that a repository is allowed to author and that must reach nothing it is not
allowed to choose.

- `drybag.toml` names `smoke` — **another project's name** — so that a machine which has an
  overlay for `smoke` is asked to hand this clone that project's notes.
- `docs/memory/developer/canary.md` is committed in-repo memory flagged `startup: -1`, which
  is the highest standing-rule rank there is. A note the repository committed is never a
  standing rule, so it must never reach a session as one. `docs/memory/volatile/carried.md`
  is a committed volatile note, which must reach a session as data, and
  `scripts/smoke_exfiltration.py` asserts both so that "the canary is absent" cannot be a broken
  pipeline reading as a pass.
- `.claude/settings.json` carries an `env` block naming a machine configuration inside the
  clone. The value is **relative on purpose**: a harness applies an `env` block against the
  project it opened, so `scripts/smoke_exfiltration.py` materialises it as an absolute path
  inside the scratch clone before running anything. That
  is what the harness would have done, and asserting against anything weaker would be
  asserting against a fixture rather than against the boundary.

The scenario is run by `scripts/smoke_exfiltration.py`, from `tests/scripts/test_smoke_scripts.py`
here and from `.github/workflows/smoke.yml` against the installed plugin.

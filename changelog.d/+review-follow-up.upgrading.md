Keys nothing read any more are gone. Delete each from an existing `stayfixed.toml`, or every
command that loads it exits 1 with the loader's refusal, `[project] has unknown key(s):
release_branch` for the first. `stayfixed doctor` warns `not-initialised`, names each among the
settings it ignored and exits 0, and a session's hooks load the file the same way:

- `[project] release_branch`. `stayfixed init` no longer writes it, and `--base-branch` writes
  `[project] base_branch` alone.
- `[paths] architecture`, `runbooks`, `adr`, `roadmap_history` and `stayfixed`, which only the
  documents earlier `init` runs wrote were placed by: `[paths] has unknown key(s): runbooks`. Their
  one remaining effect was to name `docs` as a directory documents live in, which `specs`, `plans`
  and `bugs` already do, so a project on the defaults loses nothing. A project that pointed one of
  them outside `docs/` and cites bug entries from there points `specs` or `plans` there instead.

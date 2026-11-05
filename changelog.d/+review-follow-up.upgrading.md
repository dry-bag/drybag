Keys nothing read any more are gone. Delete each from an existing `stayfixed.toml`, or every
command that loads it exits 1 with the loader's refusal, `[project] has unknown key(s):
release_branch` for the first. `stayfixed doctor` warns `not-initialised`, names each among the
settings it ignored and exits 0, and a session's hooks load the file the same way:

- `[project] release_branch`. `stayfixed init` no longer writes it, and `--base-branch` writes
  `[project] base_branch` alone.

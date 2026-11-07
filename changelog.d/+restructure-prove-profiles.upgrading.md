`stayfixed prove` is gone, with no alias, and so are the stack profiles and the key and flag only
they read:

- `stayfixed prove`. `stayfixed bugs regressions` still runs each fixed bug entry's `regression`,
  now judged by its exit code alone (below). The `Stop`-hook recipe built on `prove`
  (`examples/stop-hook/`) went with it: delete a hook you copied from it.
- the stack profiles, `[stayfixed] profile`, `stayfixed init --profile` and the profile question
  of `stayfixed init --questions`, which now asks five. The red-run note after a failed `Bash` call
  now speaks when one of the command's simple commands is a common test runner's (`pytest`,
  `go test`, `cargo test`, `npm test` and the like), whatever the stack, and names only the
  uncommitted changes in the tree: the line about stale Python bytecode is gone.

Delete `profile` from the `[stayfixed]` table of an existing `stayfixed.toml`, or every command
that loads it exits 1 with the loader's refusal, `[stayfixed] has unknown key(s): profile`.
`stayfixed doctor` warns `not-initialised`, names `stayfixed.profile` among the settings it
ignored and exits 0.

`stayfixed bugs regressions` reports each run as `passed` (exit 0), `failed` (any other exit, its
code named), `timed-out`, `interrupted` or `not-run` (the argv could not be started), where it said
`proved`, `not proven` or `refused`, and its summary ends `<m> not passed`. Every fixed entry's
argv now runs: one no runner adapter recognised was `not proven` and never started. Under `--json`
the count of runs that did not pass is `not_passed`, where it was `not_proved`, and each run's
`line` is its verdict and detail.

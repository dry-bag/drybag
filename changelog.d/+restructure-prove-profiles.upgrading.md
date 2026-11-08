`stayfixed prove` is gone, with no alias, and so are the stack profiles and the key and flag only
they read:

- `stayfixed prove`. The `Stop`-hook recipe built on `prove`
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

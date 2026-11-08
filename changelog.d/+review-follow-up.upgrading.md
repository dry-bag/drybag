Keys nothing read any more are gone. Delete each from an existing `stayfixed.toml`, or every
command that loads it exits 1 with the loader's refusal, `[stayfixed] has unknown key(s): agents`
for the first. `stayfixed doctor` warns `not-initialised`, says how many settings it
ignored and exits 0, and a session's hooks load the file the same way:

- `[stayfixed] agents`. Which harness a session runs under is read
  from the session itself, and `stayfixed setup --plugin` installs for every harness the preset
  names a marketplace for, as it did with the preset's default list.
- `[project] release_branch`.
- `[paths] architecture`, `runbooks`, `adr`, `roadmap_history` and `stayfixed`.

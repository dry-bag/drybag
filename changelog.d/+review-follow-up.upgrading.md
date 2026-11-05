Keys nothing read any more are gone. Delete each from an existing `stayfixed.toml`, or every
command that loads it exits 1 with the loader's refusal, `[stayfixed] has unknown key(s): agents`
for the first. `stayfixed doctor` warns `not-initialised`, names each among the settings it
ignored and exits 0, and a session's hooks load the file the same way:

- `[stayfixed] agents`, with `stayfixed init --agent` and the agents question of
  `stayfixed init --questions`, which now asks five. Which harness a session runs under is read
  from the session itself, and `stayfixed setup --plugin` installs for every harness the preset
  names a marketplace for, as it did with the preset's default list.
- `[project] release_branch`. `stayfixed init` no longer writes it, and `--base-branch` writes
  `[project] base_branch` alone.
- `[paths] architecture`, `runbooks`, `adr`, `roadmap_history` and `stayfixed`, which placed
  documents earlier releases of `init` wrote. Their one remaining effect was to make `docs` a
  directory `bugs check` reads citations of entry files in, which `specs`, `plans` and `bugs`
  already do, so a project on the defaults loses nothing.

`stayfixed init` writes nothing into a `stayfixed.toml` you wrote. It no longer adds a missing
`[stayfixed] version`, and no longer refuses a file the next command cannot load: that command
exits 1 naming what the file lacks, `[stayfixed] is missing required key(s): version` for this
key, and the remedy is the line written by hand. A `stayfixed.toml` `init` creates no longer says in its header that stayfixed rewrites
`[stayfixed] version`, since no command does.

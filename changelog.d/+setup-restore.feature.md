`stayfixed setup --restore` restores a machine from the private overlay its machine file records
(or `--overlay` names). It prints which of `git`, `claude` or `codex`, and `python3` or `uv` are
missing, runs machine setup, installs the plugins and marketplaces the overlay's
`machine/claude/settings.json` enables, and attaches every checkout listed in the overlay's
`machine/projects.toml` that exists. A checkout whose project is not the one its table names is
refused instead of being given another project's notes, one with no `stayfixed.toml` is attached
under the project its table names, one that is not there is skipped, and a second run changes
nothing. A recorded overlay that is gone is refused, naming it. With `--yes` it also records as
reviewed every unreviewed note of the overlay's share for each attached project, its tags' notes
included, and never a note a checkout holds; with `--sync` it switches note sync on.

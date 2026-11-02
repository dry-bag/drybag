`stayfixed setup --restore` restores a machine from the private overlay its machine file records
(or `--overlay` names). It prints which of `git`, `claude` or `codex`, and `python3` or `uv` are
missing, runs machine setup, installs the plugins and marketplaces the overlay's
`machine/claude/settings.json` enables, and attaches every checkout listed in the overlay's
`machine/projects.toml` that exists. A checkout whose project is not the one its table names is
refused instead of being given another project's notes, one that is not there is skipped, and a
second run changes nothing. With `--yes` it also records as reviewed the notes of the overlay's
share for each attached project, and never a note a checkout holds.

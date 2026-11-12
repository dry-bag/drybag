`drybag attach --check --json` names its keys as the run's `--json` does: `allow_added` in place of
`added_allow` and `rules_written` in place of `rules_to_write`. `drybag detach` no longer takes
`--machine`, which it never read; drop it from any script that passes it.

`drybag doctor`'s `memory` row now reads `~/.claude/settings.json` without `--home`, and warns, with
`drybag memory index --check` as the remedy, when that check would fail: an out-of-date index of a store that holds
notes, a file in the store that cannot be read as a note, or an index over its word budget or the harness's caps.
`drybag doctor --root` naming no directory is now refused with exit 2 before any row runs.

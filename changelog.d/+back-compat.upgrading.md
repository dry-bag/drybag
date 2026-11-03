stayfixed no longer carries code for what 0.3.x and earlier releases left on a machine or in an
overlay. A `trust.json` still holding the flat map 0.3.x wrote, a store's path to its digest, is
now refused as unreadable instead of read as holding no approval, and nothing overwrites it: delete
it, since the store approvals it holds are ones nothing asks about. The `hook-entries` row of
`stayfixed doctor` is gone: it counted hook entries and named none, so a hook a cloned repository
commits read as accounted for. The `files` row is gone: `wrapper` now reports a hook wrapper that
is not executable under a plugin root the environment names, where it runs nothing. The
`retired-deny` row is gone too, and so is the `recommended` preset's `[deny] retired` key, so
`stayfixed setup` no longer takes `Read(.env*)` or `Read(**/.env*)` out of
`~/.claude/settings.json`; if either is still there, delete it by hand, since it refuses
`.env.example` too. `stayfixed overlay upgrade` no longer removes the four files earlier releases shipped in an overlay and this one does not:
`common/memory/README.md`, `skills/attach/SKILL.md`, `common/rules/README.md` and
`hooks/hooks.json`. If any of them is still in your overlay, delete it by hand, the memory README
first, since the note reader reads it as a note.

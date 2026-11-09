# Bound repositories

One directory per repository, named by its `[project] name` — the same string that project's
`drybag.toml` carries, so the binding cannot be ambiguous.

Each holds `project.toml`, which records the repository's own remote, and `memory/`, that
project's notes. `drybag attach` compares the record with the checkout's `origin` and says so
when they differ. It refuses nothing: what binds a checkout to this directory is an id the
machine keeps, never the remote.

`drybag attach` creates both. Do not hand-write the record's remote to silence that line.

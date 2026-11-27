# Plans

One implementation plan per work package, `YYYY-MM-DD-<slug>.md`, written against the frozen
extraction design. That design document is not public: it lives in a private repository, and a
plan's references to it cannot be followed from this repository. The principles it argues from,
with their sources, are public in [docs/methodology/](../methodology/README.md). A plan's
`Scope:` line names the package it belongs to and, where that package has them, the contracts
it consumes and produces; a plan the owner cut across several packages — a wave's closure, or
one delivery spanning a lane — names all of them on that line and says why they ship together.
The two P0 documents here were copied from that repository, which keeps its own copies as
history.

Plans dated before 2026-09-28 predate the first rename and keep the first former name as the
record, and so does the plan that performs it; the plans dated from then to 2026-11-08 keep a
second former name. Read `drybag` for either in every path, command and variable.

Two plans continue in a `-part-2.md` beside them. They were split while the plugin was this
repository's root, when every file here counted against the plugin directory's 256 KiB file
limit; the plugin is now a tree generated from nine paths, `docs/` is not among them, and no
plan is split for size any more. A split plan is still one plan: it is cut at a heading, each
part ends by linking the next, each later part opens by naming part 1, and part 1's `Scope:` line
governs them all. `drybag plan check` lints each file on its own, so a path one part cites and
another declares under `- Create:` or `- Test:` is reported as a dead reference; across parts that
finding is the split's, not the plan's.

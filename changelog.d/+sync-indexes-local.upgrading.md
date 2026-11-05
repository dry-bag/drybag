The note sync no longer commits, pulls or unites a project's `MEMORY.md`: each machine renders its
own, at the start and at the end of every session in a checkout bound in overlay mode, and the
lines a session appended are harvested into their notes on that machine before its job runs, so
the notes travel instead. An overlay that still commits its indexes should untrack them (`git rm
--cached projects/*/memory/MEMORY.md`, committed and pushed once). Until that commit is taken on a
machine, the job holds an upstream change to an index there like any change outside memory, and
`doctor` gives the review command. `checkouts.json` is no longer written, and a `state.json` whose
outcome is `resolved_index` reads as unreadable once and is replaced by the next job.

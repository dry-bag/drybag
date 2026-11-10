A plate of the overlay (`common/`, a tag, a project) can hold `machines/<name>/`, a sub-plate with the plate's own
layout that applies only on the machine whose `[machine] name` in the machine file is `<name>`. It comes right after its
plate, so rules, skills, agents, hook entries, allow rules, `drybag.toml` values and notes there win over the plate's
own or add to them on that machine alone. A `machines/` directory or a `[machine] name` outside the tag shape is a note
that `attach`, `attach --check` and `doctor`'s `attached` row say.

`drybag attach` on a machine with no `claude` on `PATH`, a Codex-only one say, composes the notes
and exits `0`, saying once that the overlay's hooks, skills, agents and MCP servers were rendered
but not installed; the next `attach` that finds `claude` installs and delivers them. It exited `1`
on every run before composing anything. A `claude` that is there and fails still exits `1`.

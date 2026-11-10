---
name: doctor
description: Diagnose a drybag installation — hooks, memory store, budgets, overrides and trust. Use when a hook is silent, memory does not arrive, a check fails unexpectedly, or the user asks whether drybag is set up correctly.
---

# Diagnosing an installation

1. Run `drybag doctor --json` and read the report: fourteen checks, each with a status, a
   detail and a remedy. Between them they answer whether the repository is initialised, whether
   the hook wrapper can reach drybag at all, whether this checkout is attached, whether the
   overlay's delivery is in place and what shape its memory path has, each budget raised or
   lowered, the layer each preference and machine-owner key
   came from, a bundle that does not fit its slots, the last reasons a hook failed, whether the overlay's note sync can run, and, as
   information, an environment variable that is set and ignored.
2. Relay each finding with the remedy the report names, verbatim. Do not change settings or
   hook entries on the user's behalf — name the command that would.
3. A `skip` is not a fault, and it is not always harmless either. Eight checks skip on a
   state of the machine or of the repository: `wrapper`
   when no plugin root can be vouched for,
   `attached` when no overlay is recorded or the overlay cannot be asked, `pre-commit` with no
   overlay root recorded, `overlay-requires` with no overlay root recorded or no requirement
   declared — and those last two also skip when the overlay root this machine records is not a
   directory any more, which is the one overlay skip that carries a remedy (put the overlay
   back, or record where it is now), because the note store is broken with it — `bundles` when the note store does not resolve,
   `diagnostics` with no harness data root set, and `sync` when the machine file does not switch
   the note sync on. With no project
   configuration to read, `budgets`, `attached` and `bundles` skip
   saying so; that is one state, not several, and it brings `budgets` to the eight. Each says which
   state it is in its own detail. Report each as the state it names, and relay the remedy where
   the row carries one.
4. **`wrapper` skipping for no plugin root says where this `drybag` runs from.** A `drybag`
   installed as a package finds no plugin root while the plugin's hooks run normally, so check
   first that the plugin is installed and enabled. Where it is not, no hook entry reaches
   drybag on this machine and nothing else in the report can say so: lead with it, and relay
   the remedy the row carries.
5. When `not-initialised` warns, either there is no `drybag.toml` — the guards and this
   report work, and its remedy adds the rest — or the file loaded with some settings ignored or
   put back to the preset's, which the row names by key; relay its words and its remedy. When it
   is red, the session drops the file whole; relay the row's words and its remedy first. Every
   other row is still answered.

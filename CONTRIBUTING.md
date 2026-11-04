# Contributing to stayfixed

stayfixed's real conventions used to live only inside `docs/plans/`, which meant a first-time
contributor's pull request could be rejected on rules they had no way to read. This file is
those rules.

## The short version

```bash
uv sync                                           # once
uv run pytest -n auto --cov --cov-fail-under=92   # the suite across workers, at CI's floor
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run python scripts/mutation_oracle.py          # every declared mutation still reddens
uv run python scripts/release.py check            # version discipline
```

All five run in CI. Four of them, every one but the mutation oracle (the suite with its coverage
floor, ruff, mypy and `scripts/release.py check`), run on Linux for Python 3.11, 3.11.4, 3.12,
3.13 and 3.14 and on macOS for 3.13, which is why `pytest -q` alone will give you a green tree
and a red pull request. The mutation oracle, which is this project's headline obligation and not
an optional extra, runs in a job of its own on Linux under 3.13 (see [Tests](#tests)). CI runs
three more steps you can reproduce only from a build (`uv build`, then
`scripts/check_artifacts.py dist` and an installed-wheel render), and one job you cannot reproduce
without a global install of the harness CLI, the plugin-manifest validator; a failure in either is
ours to diagnose, not yours.

## What this project is, and what that costs a change

stayfixed treats **a repository as untrusted input**. A clone can commit a `stayfixed.toml`, a
`MEMORY.md`, a manifest, an `env` block and a tree of symlinks, and all of it reaches the code
before a human has read any of it. Three rules follow, and a change that breaks one will be
sent back however good it looks otherwise.

**The runtime imports only the standard library.** Hooks run under whatever `python3` the
wrapper finds, before any environment exists, so a third-party import works on your machine and
fails inside a hook on somebody else's. `tests/boundaries/test_layering.py` enforces this on
every supported interpreter. Development dependencies (`pytest`, `ruff`, `mypy`, `towncrier`) are
fine; a runtime one is not.

**Writes go through `fsops`.** `config.paths.contained()` decides whether a configured path
*may* be written — it gives a user-facing refusal and catches a committed symlink — and
`fsops.write_within` / `mkdirs_within` / `remove_within` then do the write through an
`O_NOFOLLOW` walk, so a component that becomes a symlink after the check cannot redirect it.
Do not add a `Path.write_text`, a `mkdir(parents=True)` or an `os.replace` on a string path to
code that puts files into a repository.

**So do questions about what is at a path.** Ask them through `fsops.is_file`, `is_dir`, `exists`
and `is_symlink`, never through `pathlib`'s methods of those names, because `pathlib`'s answer to a
fault depends on the interpreter: up to Python 3.13 it raises on a name or a path longer than the
system takes and on a directory that cannot be searched, and from 3.14 it answers `False` for both.
A clone reaches either with a committed symlink, so one command was an internal error on one
interpreter and went quietly on on the other, and a suite run on one proved nothing about the
other. The `fsops` predicates answer one way on all of them: nothing there for a path that reaches
no file, a name too long included, and a raise for a fault that leaves the question open.
`tests/test_fsops.py::test_no_module_asks_pathlib_what_is_at_a_path_a_repository_can_shape`
refuses any other call, except the few it pins with a reason (the package's own files, an
`os.DirEntry`).

**Repository bytes are data.** Anything a repository authored — a note, an index line, a
`memory.groups` entry, a refusal message built out of one — reaches the model only inside
`trust.wrap`'s delimited region. If you find
yourself putting such a string into a `Result.summary`, a `HookResult.context` or an exception message,
wrap it.

The wrap is for the model and escapes no byte, and the same string also reaches a terminal and a
CI runner, where a line break followed by `::error::` is a workflow command and an escape
sequence drives the screen. So a name the repository chose — a file name, a note's name, a
`memory.groups` entry, a TOML key — is printed through `stayfixed.printed`: `printable` where the
command's `--json` carries the name, and `quoted` in a refusal, where the message is the only
place the name appears.

**A control names its adversary and its anchor.** A refusal, an approval, a pin or a check says
whom it stops and what it trusts: the bytes or state the decision rests on, and who can write them.
If the party it stops can reach that anchor more easily than it can pass the control, the control is
a convenience, and a convenience never refuses a legitimate user and never asks again about what has
not changed: it hints, warns or reports. The base branch in CI and the git common directory are
anchors a repository cannot move; anything the agent in the session can write through its shell
is not one against that agent.

Two narrower rules follow from the same stance. The code cites each by name, and this is where
the name is defined.

### Named caps

A bound comes from one of three places. A limit a project may tune — a document's line or word
count, a note's time to live — is a key under `[budgets]`, which the base branch and the machine
owner may raise above its preset or lower below it, and a pull request may only lower when a
gate reads it. A limit the harness sets — how much of an index it loads, how many
characters of a hook's output it keeps — is a key under `[native_caps]`. Code reads both
through `Config` (`src/stayfixed/config/schema.py`). Every other bound — a subprocess's
wall-clock timeout, how many bytes of a repository-authored file are read, how deep a parser
descends — is a *named cap*: a constant in the code, almost always a module-level one with a
name, and never a configuration key. None of them is a project's to move, because each one
protects the run itself from a hung program, an oversized file or a pathological input, and a
`stayfixed.toml` is repository-authored (principle 5).

The comment beside a named cap says what it bounds and why the number is what it is. When the number
has to agree with a shipped file, the comment names that file, so a change to either is visibly a
change to both: `NEARLY_FULL` names `hooks/hooks.json`, where a bundle's slot count is raised. When no such file exists — a timeout on a hung `git`, the longest command
`bg-cleanup` will read — the comment says so rather than inventing one.

### Enumerated writes

A command's section in [docs/cli.md](docs/cli.md) names every path the command writes, in a
paragraph that opens with **Writes** (a read-only command's says "**Writes** nothing"), and the
command writes those paths and no others: a change that makes a command write somewhere new
names the path there in the same commit. `stayfixed hook`, which is internal, is held to the same
rule: its paragraph names what it keeps inside the one directory stayfixed owns under the data
root the harness hands it (`${CLAUDE_PLUGIN_DATA}/stayfixed/`, which `src/stayfixed/hooks/sink.py`
writes), and the handlers that write outside it.

Removal is held tighter. Every file or directory stayfixed removes is one it names before it looks —
a fixed name in the code, a path its ledger or manifest recorded, one its configuration computes, or
a directory above a file the same run removed — and none is found by listing a directory and
removing what the listing returned, with three exceptions, each inside a directory only stayfixed
writes, or, for the last, writes links into. The hook sink's sessions are unbounded in number, so it lists its `markers/` directory and
prunes all but the newest `MARKER_SESSIONS_KEPT` sessions. And `stayfixed detach`
removes the render directory `$HOME/.local/share/stayfixed/delivery/<id>/` whole, as `attach` does
the one its new render replaces, a directory named by the binding id and never by the ledger, which
only `attach` writes into; and `attach` and `detach` take the links they list in the composed store
`$HOME/.local/share/stayfixed/stores/<id>/`, named the same way, where only `attach` puts a link and
a file that is not one is a note the harness wrote, which neither removes. All go through `fsops`,
as every removal in a project root does. A temporary directory a command creates for itself and removes whole when
it finishes is outside the rule: nothing but that command ever wrote into it.

## Configuration

Every key a configuration layer can hold — the preset, a repository's `stayfixed.toml`, the
overlay's files, the machine file — has one class in `src/stayfixed/config/classes.py`, and the
class names the layers that may set it: the machine owner's alone (`personal.*`, `guards.*`), a
preference, a session's parameter, a gate's parameter, the repository's alone, or
the plugin's. `classes.resolve` applies the classes over a stack of layers — a layer a key's class
does not admit contributes nothing to it — and so decides who may set a key and gives `doctor` the
layer each value came from; it builds the owner's layer from the preset and the machine file, but
the project's `Config` is still built by `config.loader`, which merges `stayfixed.toml` over the
preset and folds the owner's layer in. So a field added to a section of
`src/stayfixed/config/schema.py` needs its row in `CLASSES` in the same change:
`tests/config/test_classes.py` derives every key from the schema's dataclasses and reddens on one
with no class. Choose the narrowest class that is true of the key: a gate's input is never a
preference, or a pull request would choose what it is judged by.

## Areas

An area is a subpackage of `src/stayfixed/` that the CLI frame, the hook registry and `doctor`'s
report discover by name — there is no shared registry to edit for an area to be found. A new area
joins its side in `src/stayfixed/areas.py` (below), which the boundary rules read and discovery
does not, and, if it publishes an `api.py`, the list of surfaces `tests/test_surfaces.py` pins.
One more table names areas, `GROUP_OF` in `scripts/mutation_oracle.py`, and it is a deliberate
exception kept for a reason outside the code ("Tests" gives it): it groups their mutation entries
into files, and a new area needs no row there: its entries go in the group its path falls into.

Today the discovered ones are `attach`, `docs`, `doctor`, `guards`, `hints`, `hooks`,
`ledger`, `memory`, `overlay`, `project`, `setup` and `sync`, and every module under
`src/stayfixed/` sits on one of three sides, which `src/stayfixed/areas.py` names. **Delivery**
(`DELIVERY_AREAS`) is the private layer, a machine's setup and the session hints:
`overlay` renders and upgrades the private overlay; `attach` binds a repository to one, and its
`detach` takes back what `attach` wrote while the overlay keeps its record of the binding; `memory`
keeps the notes; `setup` a machine's configuration; `sync` the unattended commit, fetch and push
of the overlay's memory notes (the session triggers, a detached job and its `doctor` row), switched
on per machine; and `hints` the session hints
(the background-cleanup hint, the red-run note and the command scanner they share). The **pack**
(`PACK_PACKAGES`) is the methodology's records and checks: `ledger` keeps the bug ledger, `docs`
the documentation and plan lints, and `guards` the commit-message rules and the test-run checks;
and `project` holds the shipped project templates and `init`, the command that writes a
repository's scaffold from them. Every other module is the **core**,
which both sides share, `cli.py` and the subpackages that are not areas included: its areas
(`CORE_AREAS`) are `hooks`, the dispatcher every hook event goes through, and `doctor`, which
reports on what every other area left behind and repairs none of it. (`config`, `presets`, `release`, `scaffold`, `templates` and
`trust` are subpackages and not areas, and `harnesses` is a module — area discovery does not find
them, because they carry none of `commands.py`, `hooks.py` and `doctor.py`. `release` still
publishes an `api.py`, which holds what an installed stayfixed reads about its own releases: the
tags it pins; `trust` publishes one too, over every approval a person gave on the machine, kept in
one record that `memory promote` writes.)

The rules between them: either side may import the core, and otherwise no import crosses a side —
the core imports neither side, and neither side the other — through an `api.py` or not, at module
level or inside a function, but for the statements pinned in `tests/boundaries/test_delivery.py`, so
a side can be reworked without touching the core or the other side. The core may name either side's
paths and configuration keys — the `.stayfixed/` namespace and the machine file's keys are the
core's — and may not import either side's code or call its behaviour except through discovery, which
is how any area plugs into the core: the CLI frame, the hook registry and `doctor`'s report import
an area's `commands.py`, `hooks.py` and `doctor.py` by name and call the `register()` each
publishes, without knowing which area it is, and the bullets below are that contract. The crossings
that still exist are pinned one table per direction, each row with what removes it. A row is one
import statement and the names it takes, held as a multiset in both directions, so
`test_the_core_imports_neither_side_but_where_pinned` and
`test_delivery_and_the_pack_import_each_other_only_where_pinned` refuse a new crossing, a second
statement beside a pinned one, a pinned statement that takes one more name and a pinned row whose
import has gone alike. `test_every_area_is_on_exactly_one_side` puts every discovered area on
exactly one side and refuses a listed name that names nothing.
`scripts/` is repository tooling and stays under the `api.py` rule alone. The rules this section
names live under `tests/boundaries/`, a file for each (discovery, the `api.py` surface, delivery and
the import layers), and share one reading of the syntax tree, `astscan.py`, which has cases of its
own. `scripts/` has one rule of its own beside them: no script imports another.
`scripts/publish_plugin.py` runs `scripts/plugin_tree.py` and `src/stayfixed` read out of the tag's
objects, so nothing it runs may reach for a sibling script that extraction does not carry, and a
constant two scripts share is copied into each and held equal by a test rather than imported.
`tests/scripts/test_script_imports.py` holds the rule over every script and the launcher, with one
exemption it names: `smoke_exfiltration.py` imports `smoke_hooks`, both CI smoke drivers run from
the checkout. It reads import statements and judges each by its name, so a script run through
`runpy` or loaded through `importlib` is not seen, and `sys.path` is not followed.

Those rules read import statements, so a module named to `importlib.import_module` is invisible to
them, and two rules of their own in `tests/boundaries/test_delivery.py` hold that door for every
module, on either side or in the core. The first reads names: no module names `import_module` or
`__import__`, a module's own `__spec__` or `__loader__`, the finders on `sys` (`meta_path`,
`path_hooks`, `path_importer_cache`), `sys.breakpointhook`, or a builtin that runs text (`exec`,
`eval`, `compile`, `breakpoint`, `__builtins__`) wherever it is the builtin in that scope, under any
alias, except `areas.py`'s two imports by name. `__builtins__`, which every module carries, is also read off any module
(`json.__builtins__`) and in a `from` of any module. Only a function's own binding, a
comprehension's variable or an import from a module other than `builtins` hides such a builtin, in
its scope and the scopes it encloses. Python looks a module's or a class body's names up at run
time, where a binding may not have run, may have been deleted, or may be the builtin itself
(`exec = exec`), so a binding of one of these names there hides nothing and is a row of its own, to
pin or rename; a walrus in a comprehension binds in the scope around it. A docstring is prose and is
not read. The second reads imports: a module imports the standard library from the modules
`STANDARD_IMPORTS` lists, none of which imports a module named by a string but through a name the
first rule reads, and any other import (`importlib` and `pkgutil` among them) is a row of
`MACHINERY_IMPORTERS`, with what each file reaches in it. `importlib.resources` is held too: `files`
imports the anchor it is handed when that names a module, so a module calls it only on its own
package, `__package__` or `"stayfixed"`, and every other read of it is a row.

Every call of `area_modules` or `area_imports` names `commands`, `hooks` or `doctor` as a literal,
and is made by that submodule's one reader: `cli.py` asks for `commands`, `hooks/registry.py` for
`hooks` and `doctor/registry.py` for `doctor`, pinned in `DISCOVERY_CALLERS`. No other module refers
to `cli.discover_registrars`, which hands on what discovery found.

These rules are a tripwire, not a proof: they catch a crossing written the ordinary way. They cannot
see an attribute chain through an allowed module (`dataclasses.inspect.importlib`, or
`urllib.request` read off the `urllib` that `import urllib.parse` binds), a module already in
`sys.modules`, a loader or finder reached by a computed name (`getattr(sys, "meta" + "_path")`),
an import in a module or a class body that fails and is caught, which hides a builtin the first
rule then takes for the file's own, code built from text at run time, or a string an allowed
module evaluates (an annotation built at run time and handed to `typing.get_type_hints`). Review is
what holds those.

What source cannot show is when a pardoned statement runs, so
`test_in_isolation_no_core_module_loads_either_side` imports every core module in a clean
interpreter and refuses any module of either side among what it loaded: the core loads a side only
when a command asks for it.

The packages under `src/stayfixed/` import one another without a cycle
(`test_the_packages_import_one_another_without_a_cycle_at_module_level`), counting each import that
runs when its module is imported. An import inside a function, which defers a load until a command
asks for it, and one under `if TYPE_CHECKING:`, which never runs, are not counted. A leaf that two
packages share, such as the path grammar in `grammar.py`, lives where neither has to import the
other for it. The modules import one another without a cycle too, and there an import inside a
function counts (`test_the_modules_import_one_another_without_a_cycle_even_inside_functions`):
deferring a load keeps a module from being left half-initialised, and does not make two modules that
need each other one layer. An import of a submodule counts as an import of every package above it
too, since Python runs each package's `__init__.py` first.

- `commands.py` with a `register(groups)` gives the area its CLI group.
- `hooks.py` with a `register() -> list[Handler]` gives it hook handlers. Every import inside a
  handler body, never at module level: `tests/boundaries/test_discovery.py` asserts that discovery
  in a clean interpreter imports neither the configuration layer nor the presets.
- `doctor.py` with a `register() -> Contribution` gives it rows in `stayfixed doctor`'s report: its
  `(name, check)` pairs are asked after the core's own checks, in area-name order, each with the
  report's `Context` and through the same guard, so a check that raises costs its own row and not
  the report. An area that cannot contribute is held to one policy, whatever the cause: a
  `doctor.py` that fails to import, a `register()` that raises or returns anything but a
  `Contribution` of `(name, check)` pairs, and one that contributes a name already in the report — a
  core check's, an earlier area's, or another of its own, since a check's name is unique in the
  report — each puts one red row named after the area where its rows would have been (numbered,
  `<area> (2)`, when the report already has that name), and the rest of the report stands.
  `register()` is called once per report, so anything it creates for its checks — an area that
  reads the note store creates a value that resolves it at most once — is fresh for every report.
  What the core owns and several areas read is on the `Context` instead: `Context.overlay_root`,
  the machine file's `[overlay] root`, is read at most once per report for every area that asks
  the `Context` for it. That is the one answer it caches: code an area reaches through its own
  modules, such as the binding and the note store, resolves the root again.
  `Contribution`, `Context` and `Row` come from `stayfixed.doctor.api`, and, as in a `hooks.py`,
  every import sits inside a function body; `tests/boundaries/test_discovery.py` holds that one.
- `api.py` is the area's import surface. Other areas import from it and from nothing else, and its
  `__all__` must equal exactly what it imports — a test parses the file and checks, and
  `tests/boundaries/test_api_surface.py` walks every module under `src/stayfixed/` and `scripts/`
  and fails on an import that reaches past one. The rule holds every package that publishes an
  `api.py`, an area or not (`release` is held to its surface like any area). The list is what consumers
  actually reach for, not what the area finds tidy: a consumer that needs something absent from it
  grows it deliberately, in a commit that says which consumer and why.
- **`stayfixed.hooks.api` is the one exception, and it is structural rather than drift.** That
  module *defines* the vocabulary two areas share — `EVENTS`, `HookEvent`,
  `HookResult`, `Handler`, `HandlerFn`, `Sink`, `NullSink` and the sink's on-disk layout —
  instead of re-exporting it, because `hooks.dispatch`, `hooks.sink`, `hooks.registry` and every
  area's `hooks.py` import *it*: a name defined in one of those modules and re-exported from
  `api.py` would be an import cycle, not a tidying. So in the one area that ships the common
  vocabulary the rule runs the other way — **a name two areas share is defined in `api.py`** —
  and its `__all__` lists what it defines. No other area may read this as licence: a consumer
  still imports `stayfixed.hooks.api` and never `stayfixed.hooks.dispatch` or `.sink`.
- Every area is a regular package with an `__init__.py`. `pkgutil.iter_modules` does not yield a
  namespace package, so one without it is invisible to all three discovery paths.

stayfixed is language-neutral: no module names one stack's runner, build artifacts or package
manager except the pardons `tests/test_language_neutral.py` lists, each with its reason, and a new
mention joins that list with one.

The agents are core knowledge too, held in one place. A harness — Claude Code, Codex — is a value in
`harnesses.HARNESSES`, and the `hooks` area answers through it: `stayfixed hook` asks
`harnesses.detect` which value it runs under and shapes its stdout with that value's `render`, and
the event a handler reads does not say which value that was. That is all detection decides, and
`detect`'s docstring says why. Adding a harness is adding a value — a positive `detects`, its
project-root and plugin-root variables, its `render`, its settings files, its memory directory if it
keeps one, and its `reach`, the tier each enforcement surface holds at under it — and nothing that
reads those needs an edit: the README's table of what each agent enforces is held equal to every
value's `reach` by a test. It is not only a value: what a new
harness still touches outside the registry is listed in the module docstring of
`src/stayfixed/harnesses.py`, and `tests/test_harnesses.py` holds that list to every string in the
package that names a harness.

Two top-level trees are documents rather than areas. `skills/` holds the Agent Skills this
plugin ships and `agents/` the agent files; [skills/README.md](skills/README.md) is their
contract — a skill body is **action language** and never names a harness tool, a `SKILL.md` is
capped at 80 lines with the detail in `<skill>/references/`, and every `stayfixed …` invocation
in a skill must parse against the real parser or be listed in `NOT_YET_SHIPPED` against the
area that will ship it. `tests/skills/test_skills.py` holds all three, and the change that
ships a command deletes its `NOT_YET_SHIPPED` entry.

**The payload guard judges the generated tree.** `tests/test_payload.py` holds the plugin tree to
the directory's file rules on every pull request — the 256 KiB size, the 512-file count, symlinks,
binaries, names — and reads it from the commit, as `scripts/plugin_tree.py` does; a file outside
the plugin's paths is not judged, because it does not ship. `scripts/release.py check --tag` holds
the count again on the commit a release is cut from. A file the runtime needs outside
`PLUGIN_PATHS` is added there, in the same change, or the plugin repository never holds it and an
install breaks; the install smoke runs every hook entry from the installed tree, so CI finds an
omission before a user does ([RELEASING.md](RELEASING.md), section 2, says where the tree goes).

## Tests

**A branch that decides a verdict, a containment or a data-loss path ships with a declared
mutation that reddens its test.** Write the assertion, break the line of source it is about, watch
it fail, put the source back, and add that mutation to `mutations/`, so the check is reproducible.
Other assertions need neither an entry nor a sentence saying why none exists, and deleting a
control deletes its entries:

```bash
uv run python scripts/mutation_oracle.py            # every declared mutation
uv run python scripts/mutation_oracle.py fsops      # only the matching ones
uv run python scripts/mutation_oracle.py --jobs 2   # at most two entries at a time
```

Each entry names one file, one exact line to change, and the tests that must fail when it does.
The keys are `name`, `file`, `before`, `after` and `reddens` — `reddens`, not `tests`, and
`name` is required: the oracle raises `KeyError: 'name'` on an entry without one. `reddens` is an
any-of list: an entry is caught when at least one named test goes red, so name only tests that do,
and give a test that must redden on its own an entry of its own. `before` is an
exact substring of the file and `after` is what replaces it, so an entry whose `before` has
drifted is a finding rather than a skip. The oracle proves `HEAD`: it applies every
mutation to a throwaway worktree, so it never writes your working tree, and it refuses when a
mutated file — **or any test file that a selected entry's `reddens` names** — has uncommitted
changes, because that edit is work the run cannot see. Which is why a mutation run comes
*after* the commit it is about, and why an uncommitted test edit mid-change stops it too.

The oracle proves several entries at once: one worktree per job, each job proving one entry at
a time in a checkout no other job touches, with as many jobs as the process has CPUs up to four
unless `--jobs` says otherwise. So a test that a `reddens` names runs beside other tests in
other processes and must be safe to — no shared path outside `tmp_path`, no wall-clock bound
that load could break. A test that fails under contention fails on the mutated run for a reason
that is not the mutation, and that reads as *caught*. The product's own bounds on `git` are one
such clock, so `tests/conftest.py` lifts every `git_run` bound to a floor of its own, through
the environment variable `gitenv.FLOOR_VARIABLE`, which the product honours only as a raise
(`src/stayfixed/gitenv.py` says why that is safe). A `stayfixed` the suite starts as a separate
process gets the same floor: a spawner that strips the developer's own variables takes
`tests.floor.developer_free_environ()`, which keeps the floor, and one that builds its child's
environment from nothing adds `tests.floor.floor_env()`. A test about a bound running out
removes the variable and passes a small bound of its own, as `tests/test_git_run.py` does. The
floor also hides a bound shrunk below git's own latency, so
that file holds every bound a `git_run` call passes to at least a second, and a bound you add is
a row in its table.

```toml
[[mutation]]
name = "the containment walk stops refusing '..'"
file = "src/stayfixed/fsops.py"
before = "        if part in (_PARENT, _HERE):"
after = "        if part in (_HERE,):"
reddens = ["tests/test_fsops.py::test_a_parent_component_never_leaves_the_root"]
```

The set is one file per group of the tree, and an entry goes in the group file its `file` routes to:
`GROUP_OF` in `scripts/mutation_oracle.py` maps path prefixes to groups, the longest matching prefix
winning and the empty prefix's group taking anything no other prefix matches. The groups are coarse
because they were sized for the 512 files past which the plugin directory holds the version for a
reviewer, while this repository's root was the plugin and every tracked file counted against them:
one file per area would need no table, and would have spent about twenty of those 512 where eleven
do. The plugin is now published from a repository of its own, whose root is the tree
`scripts/plugin_tree.py` generates from the paths its `PLUGIN_PATHS` names, and `mutations/` is not
among them, so that limit no longer reaches these files, and there is no size cap on a group file.
`GROUP_OF` stays all the same: regrouping the declarations into one file per area would rewrite
every entry's history and collide with every open branch's entries, for no reader's gain. It
remains the one exception to "no shared registry" under "Areas", and it is stated as such there and
beside the table. `tests/scripts/test_mutation_oracle.py` reddens on an entry in the
wrong file.
A comment that cites an entry names the set and the entry's quoted name — `mutations/`'s "the
containment walk stops refusing '..'" — and never its group file, so a regroup leaves the comment
true. That makes a name a reference, and two things hold it to one: the oracle refuses a name two
entries share, and `tests/scripts/test_mutation_oracle.py` resolves every such citation in a
tracked file outside `docs/plans/` against the declared names, so renaming an entry is an edit to
every comment that cites it. Further names follow the first under the same anchor, joined by a
comma, `and` or `or`, or as an arrow list that says what each one breaks (`"a" -> …; "b" -> …`).
That file also reads every quote of a declared name in those files and refuses one the reader does
not read, a name after prose, in a bulleted list or in parentheses among them, and an anchor that
reads no name, because a name nothing reads can be renamed away with every test green.

A comment in a group file speaks for the entry below it and for the entries after that which carry
no comment of their own — the file's header speaks for the file and heads no entry — and never by
position for any other: an entry is named, never "the one above". A block split across group files
is stitched by quoted name: each entry that sits in a different group file from the comment that
speaks for it carries a one-line pointer, beginning "In the block led by", that cites the block's
lead entry and says the comment's gist, and the citation test holds that pointer like any other
citation.

The oracle sweeps before it runs. A killed run — `kill -9`, a CI timeout, a cancelled agent —
cannot run its own cleanup, and `git worktree prune` does not collect what it leaves: prune only
drops entries whose directory is gone, and a killed run leaves its directory standing. So the
first thing a run does is drop every `stayfixed-oracle-*` checkout but its own, naming on stderr
what it dropped.

CI runs the whole set in a job of its own, called `oracle`, on one configuration —
`ubuntu-latest` with Python 3.13 — while the tests go on running on all six. The oracle proves
that a mutation reddens a test, which is a property of the code and of the tests rather than of
the platform, and at 657 to 751 s a run it was 76% of the `checks` job and had pushed it past
its fifteen-minute bound. Its own job has its own budget, and `ci.yml` says what that budget
buys in further entries; `test_the_mutation_oracle_has_a_job_of_its_own_with_a_budget_that_fits`
reddens when the set outgrows it, so you find that out here rather than from a cancelled job.

Say plainly what narrowed: your local run is still the full check, and CI's guarantee is now
that the set holds on Linux under 3.13. A mutation that holds there and not on macOS, or not
under another interpreter, would reach `main`, where before it would have been caught in the
pull request.

A pull request that changes only documents, or Python comments, narrows further: the suite runs on
that one configuration alone, and the oracle, the plugin validator and the install smoke skip. A
document is a path under `docs/` or `changelog.d/`, or a Markdown file at the root; Markdown under
`skills/` or `agents/` is code, since the plugin validator reads it, and so is a docstring. Tests
read documents and comments, and ruff, mypy and coverage read the comments that steer them, so the
suite still runs once. `scripts/ci_scope.py`, run by the `changes` job in `ci.yml` and `smoke.yml`,
decides it, and decides it closed: a renamed file counts under the name it left, a Python file
that does not tokenize counts as code, and any answer but an explicit `false` runs everything
(`tests/test_ci_scope.py`). Every other leg still starts and reports, because branch protection
requires each by name. A mutation entry whose text such a change edits fails on the next pull
request that runs the oracle.

A possessive repeat (`*+`, `++`) of one character or class may stand in any pattern; of a group,
only where every pass is single characters and anchors followed by repeats of one character that
may match nothing, or one repeat of one character that needs at most one, alone
(`(?:\.[a-z][a-z]*+)++`, never `(?:\.[a-z]++)++` or `(?i)(?:[a-z]{2,}|-)*+`). Python 3.11.0 to
3.11.4, Debian 12's among them, go on from where a failed pass of any other shape stopped (fixed
in 3.11.5), and no atomic group stands anywhere, since it keeps the record a possessive repeat
drops. `tests/test_patterns.py` holds the shape, and CI's `checks (ubuntu-latest, 3.11.4)` leg
runs every reader's tests on an interpreter with the bug.

Run the oracle on Python 3.12 or later. Two entries, a function's and a class's type parameters
going unread, are caught by a case written in 3.12's syntax for them, which is skipped below
3.12, so on 3.11 both survive and the run reports them.

Four things are findings: a mutation that *survives*; one whose `before`
line no longer exists, because the assertion and the line it is about have drifted apart; one
whose `before` line appears more than once in the file, because then the entry does not name a
line; and one whose named tests do not pass on a clean tree before the mutation is applied,
because a test that is red, skipped or misspelled cannot prove anything about a guard. A fifth is
not a finding about your entry but about the mutation you chose: one that stops the named tests
from *running* — an `after` that breaks the import, say — is reported as proving nothing, because
pytest's non-zero exit there says only that something went wrong. This is not a coverage
substitute; `--cov` is the breadth measure. It is the set of guards whose load-bearingness has
to be proven rather than merely executed, which is exactly the distinction that let
`fsops.open_within` be covered by twelve tests and contain nothing.

Writing the oracle found two entries that did not hold, which is the argument for having it.

Name a test after the behaviour, not the function:
`test_a_corrupt_record_is_never_overwritten`, not `test_recorded`.

Comment *why*, in the test. Most of this suite's comments name the defect the test exists to
catch, which is what makes a later reader able to tell a load-bearing assertion from decoration.

**The neutrality gate walks every tracked file.** `tests/test_neutral.py` holds the whole tree
to a denylist and three shape rules: no string that identifies the repository these guards were
extracted from, no personal email address, no bare abbreviated commit id, no vendor-prefixed
branch name (`codex/…`, `claude/…`, `cursor/…`). The denylist is stored as digests rather than
as the strings, because a gate that lists what it is hiding publishes it in the very repository
the rule is about — so a hit reads `token be440e8c9338 at 812` and not the word you wrote.

```bash
uv run pytest tests/test_neutral.py
uv run pytest "tests/test_neutral.py::test_no_tracked_file_carries_a_project_identifying_string[docs/cli.md]"
```

The second form is how you ask about one file: the walk is parametrised and the case id is the
file's own path from the repository root.

The number after `at` is the character offset of the first matching window in the lower-cased
file, and the entry's own length is what you read from there: slice that many characters out of
your file at that offset and you are looking at the string the gate refused. Characters and not
bytes, because the sentence before this one is the instruction and an em dash is three bytes:
the gate used to report the byte offset, and on a line in this repository's own house style the
two differed by four. Two entries are four characters long, which is why the offset is printed
at all — a four-character window is not something a contributor can guess. Rewrite the line;
do not add an entry to the exemption.

A test must never read or write the developer's real `~/.config/stayfixed/`, `~/.claude/` or
`~/.codex/`. Pass `--machine` to a command, `machine=` to `resolve`, `home=` where a function
takes one, and use `tmp_path` for everything else. A test must not shell out to `gh`, `claude`,
`codex` or `pre-commit` either: `stayfixed.runner.Runner` is the seam those calls go through, and a
stub records the argv, which is the part of them that can be wrong in a way somebody notices.

## Commits and changelog

Conventional-commit subjects (`feat(memory):`, `fix(scaffold):`, `docs(plans):`), describing
**intent** rather than mechanics. `fix(memory): stop a half-built worktree tree and a refusal
from vanishing` is the house style; `fix: update worktree.py` is not.

User-visible changes need a towncrier fragment in `changelog.d/`, named
`+<slug>.<type>.md` where type is `feature`, `fix` or `change`, or `upgrading` for what a caller
of the previous release has to change, which the release notes open with. The leading `+` is
towncrier's orphan prefix, and it is not decoration: without it towncrier reads the slug as an
issue reference and prints it in parentheses at the end of the bullet, so the release notes
everyone reads would carry a file-name slug that means nothing to them. Write the fragment as a
release note someone outside the project can read — not as a note to yourself about the change.

`uv run python scripts/release.py check` cross-checks the version across `pyproject.toml`,
`uv.lock`, the package, both plugin manifests, `CHANGELOG.md` and the marketplace entry's `ref`.
It runs in CI; run it before you push. It is this repository's own tooling and not a command
stayfixed ships, as are its `notes` and `pin` beside it ([RELEASING.md](RELEASING.md)
says when each runs).

## Plans

Substantial work is planned first, in `docs/plans/YYYY-MM-DD-<slug>.md`, against the extraction
design. That design document is not public yet — it lives in a private repository — so a plan's
references to it cannot be followed from here. You do not need a plan for a bug fix or a
documentation change; open an issue or a pull request and say what you found.

The delivered plans in `docs/plans/` are a record, not a work list. Their `**Interfaces:**`
blocks are kept current and are what later work builds against; their code blocks are
as-planned and may differ from what shipped.

## Security

Do not open a public issue for a containment bypass or a trust-gate bypass. See
[SECURITY.md](SECURITY.md).

## Code of conduct

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).

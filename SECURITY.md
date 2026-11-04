# Security policy

stayfixed has an explicit threat model: **a repository is untrusted input.** A clone can commit
a `stayfixed.toml`, a `.claude/settings.json` `env` block, a `MEMORY.md`, a `.stayfixed/manifest.json`
and a tree of symlinks, and every one of those reaches stayfixed before any human has read it.
So a bug that lets repository-authored bytes reach the model as instructions, or lets a write
land outside the project root, is a security bug here even where it would be a nuisance
elsewhere.

## Reporting a vulnerability

**Use GitHub's private vulnerability reporting:**
<https://github.com/stayfixed/stayfixed/security/advisories/new>

That opens a private advisory only the maintainers can see. Please do **not** open a public
issue for anything in the list below — the public issue tracker discloses a containment bypass
to every user at the moment it is reported, including the ones who have not upgraded.

If private reporting is unavailable to you for any reason, say so in a public issue **without
the details** ("I have a security report and cannot use private reporting") and a maintainer
will arrange another channel.

### What to include

A proof of concept is worth more than a description. The most useful shape is a repository — or
a script that builds one — plus the command you ran and what you observed. Say which operating
system and Python version, because two of the containment paths behave differently on Linux and
macOS by design.

### What to expect

This is a small project with a single maintainer, so please read these as intentions rather
than guarantees:

| | |
|---|---|
| First response | within 7 days |
| Assessment and a plan | within 14 days |
| Fix released | as soon as it is ready; you will be told the date |
| Credit | in the advisory and the changelog, unless you ask otherwise |

## What counts

In scope, and treated as security rather than as an ordinary bug:

- **Containment.** Any write, or any read that feeds a write, that lands outside the project
  root or outside the machine owner's own store — through `..`, an absolute path, a symlink at
  any component, a TOCTOU window, or a configured value that reaches no guard.
- **The data region.** Any way repository-authored text reaches the model outside `trust.wrap`'s
  delimited region, or as a standing rule — including through a channel stayfixed hands to the
  harness.
- **Marker forgery.** Any note, index entry or configuration value that can close or forge the
  repository-data region it is wrapped in.
- **The machine anchors.** Any way a repository can choose which machine configuration file,
  overlay root or `trust.json` stayfixed reads — for example through an environment variable a
  committed settings file can set, such as `STAYFIXED_CONFIG`.
- **Destruction.** Any way a repository, or an ordinary mistake, silently destroys the machine
  owner's own state: the trust record, a hand-edited file, or a hook configuration stayfixed did
  not write.

Out of scope:

- Anything that requires the attacker to already be able to write to the machine owner's home
  directory or to a directory on their own `PATH`. stayfixed runs the `python3` and the `git` on
  your `PATH` by design, in a hook as at a terminal. In the commands an agent runs through its own shell tool, `PATH` is the harness's to choose, and that
  includes which `stayfixed` runs, and so which `git` it runs, which nothing inside stayfixed can
  decide. A `PATH` a trusted folder's `env` block sets is the harness's boundary, as the last item
  below says.
- `HOME` choosing git's global configuration (`$HOME/.gitconfig` and `$HOME/.config/git/config`)
  and stayfixed's machine files under `$HOME/.config/stayfixed`. stayfixed follows `HOME`, and
  hands its `git` the environment's `HOME`, as it runs the `git` on its `PATH`, so that your
  `safe.directory` and excludes answer, and a direnv, mise or devcontainer environment that
  sets it is the person's own, the same class as `PATH`. Claude Code never applies `HOME`, or any
  `XDG_*` variable, from a project's or a local `env` block: its settings reference says so under
  "Variables Claude Code ignores in `env`", and Claude Code 2.1.293 was measured keeping the real
  `HOME` and an empty `XDG_CONFIG_HOME` in project and plugin hooks. `XDG_CONFIG_HOME`, git's other door to that
  configuration, is dropped before any `git` runs.
- An agent with an unsandboxed shell writing an approval itself. An approval in `trust.json`
  holds against a repository's bytes: stayfixed never writes the record from them, and a clone, a
  pull or a pull request does not reach it. A repository whose hooks
  the harness runs is code running as you, which can write any file you can (the last item
  below). An agent that can run any command as you can also write any file
  you can, the record included, and stayfixed neither stops nor checks that: the harness's sandbox
  is that boundary, and `stayfixed setup --approval-boundary` prints what to set under Claude Code.
  Even an agent the sandbox confines keeps a channel no record closes: Claude Code's documentation
  does not list a project's `CLAUDE.md` or `AGENTS.md` among the paths its sandbox keeps from the
  agent's own writes, and Claude Code loads the first as instructions and can load the second,
  through an import or its project instructions setting (read in the documentation, not
  measured).
- A repository being able to make stayfixed **refuse** — suppressing memory. Undesirable, and an
  ordinary bug, but not a vulnerability: the resolver fails closed on purpose.
- Findings in a dependency that stayfixed does not reach; it has no runtime dependencies.
- A variable the dynamic loader reads (`LD_PRELOAD` and `LD_LIBRARY_PATH` on Linux,
  `DYLD_INSERT_LIBRARIES` and `DYLD_LIBRARY_PATH` on macOS) reaching a hook, from a committed `env`
  block or anywhere else. The loader acts on the hook wrapper's own shell before its first line, so
  no wrapper can refuse it. On macOS the wrapper's `/bin/sh` is SIP-protected and drops `DYLD_*`
  before anything below it starts; a shebang that loses that protection is in scope.
- `SHELLOPTS` and `PS4` reaching a hook. bash, `/bin/sh` on macOS and on the Linux distributions
  where it is bash, reads both at start-up, and with `xtrace` in `SHELLOPTS` it expands `PS4`
  before every command, so `PS4='$(program)'` runs that program. Measured against `/bin/sh`
  (bash 3.2.57) directly: the program ran in a `sh -c` handed a hook's command line, before that
  command started, and in a script whose first line was `set +x`. The shell that runs a
  shell-form hook command is the harness's, and the wrapper's own `/bin/sh` acts on both before
  its first line, so, as with the loader's variables, no wrapper can refuse them. Claude Code does
  not filter them either, by design: its settings reference applies an `env` block to every
  session and its subprocesses, and once you trust a folder, that folder's `env` block and its
  hooks run in your shells before stayfixed starts. Trust a folder in Claude Code only as far as
  you would run its code.

## Supported versions

stayfixed is pre-1.0. Only the latest released version is supported; fixes land on `main` and in
the next release rather than being backported.

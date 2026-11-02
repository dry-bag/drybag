"""Refuse a write or removal git would never show, at a place a committed `[paths]` value chose:
one guard for `init`, `upgrade` and `uninstall`.

A managed region is inserted into whatever file its `[paths]` key names, recorded or not, and a
whole file is overwritten or removed while its bytes are the ones a record states. Both the
`[paths]` value and the record are committed, and the promise that makes that acceptable is that
the diff shows the result. For a file git ignores it does not: a pulled commit setting
`agents_md = ".env"` had `upgrade` report `region_update .env (refreshed)` and append the region
to a git-ignored `.env`, and `git status` showed only the manifest. With a record carrying the
digest of a predictable ignored file (a tool-generated marker), the same commit had `uninstall`
delete it or `upgrade` overwrite it. Nothing git ignores can be given back by git either.

**The rule is exactly three conditions, and a planned write or removal is refused only when all
three hold.** Its file exists: creating a file changes nothing that was there, and removing one that
is not there removes nothing. Git ignores it. And its place was chosen by a `[paths]` value, that
is, it is not a place this build could put that artifact under the preset's own paths
(`_preset_places`), asked of that artifact's id and no other's. A fixed name (`CLAUDE.md`,
`stayfixed.toml`, `.gitignore`, the workflow, a harness's rule) and a preset-default place are never
refused: no repository value chose them, and a person may well keep `CLAUDE.md` in a global excludes
file or `stayfixed.toml` in `.git/info/exclude` on purpose. A first version refused every ignored
target, which refused those setups outright and left `uninstall` no way to take back a `CLAUDE.md`
stayfixed wrote there. The retirement a record can steer only ever reaches a target `could_write`
lists, and those beyond the preset's are `[paths]` values, so the `.env` case and the forged-record
case stay refused.

**What anchors "the preset's place", and what a repository can move.** The places are
stayfixed's own: the `[defaults.paths]` of a preset this build ships, fed through this build's
`project_templates`, whose `could_write` lists every target it could produce for each id. The
one repository input is `[stayfixed] preset`, and `presets.load_preset` accepts only a preset this
build ships, so a clone can choose among stayfixed's anchors and cannot author one. Nothing on
the disk is read to compute them, so a path this configuration never uses cannot refuse the run
(a symlinked `docs/` under `[paths]` values that all live elsewhere did, through the trail's
`contained()`), and they are computed only once some target qualifies.

One `git check-ignore`, before anything is written, dry run included; the refusal names each file
through `scaffold.printable`, the bound every report prints targets through.

**Ignored means what git would hide.** `check-ignore` consults the index, so a tracked file that
happens to match an ignore pattern is not ignored here: git shows every change to it. That is why
this is not `--no-index`, which `docs.trail` uses to ask about patterns alone.

**`LOCAL_ARTIFACTS` is exempt**: `[artifacts] local` asks for exactly that directory, which the
footprint's ignore block keeps out of git on purpose.

**No repository, no guard.** Outside a git work tree there is no diff for a change to hide
from, and every write still goes through `contained()` and the `O_NOFOLLOW` walk. Inside one, a
`check-ignore` that answers neither "some matched" nor "none matched" refuses the run before any
write (`DECLINED`), dry run included, because a guard that cannot answer must not read as a pass,
and a repository can choose either way of not answering. git reads every `.gitignore` along each
path it is asked about, so a commit holding a deep path under large `.gitignore` files runs it
past `git_run`'s bound (`-1`, no answer), and git answers a batch holding a path inside a
submodule with exit 128; a no-answer that was only a note let a pulled commit write past the guard
to a git-ignored `.env`. A `git` slow under load or not installed is refused the same way, and
the refusal says to run the command again. Whether this is a work tree at all is read off the disk
(`gitenv.in_work_tree`) and never asked of the same `git`, which fails the same way under the same
load: a `rev-parse` that timed out beside the `check-ignore` read as "no repository" and let the
write through with nothing said.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

from stayfixed.config.loader import preset_defaults
from stayfixed.config.schema import Config
from stayfixed.errors import Refusal
from stayfixed.gitenv import git_run, in_work_tree
from stayfixed.project.templates import project_templates
from stayfixed.release.api import Resolution
from stayfixed.scaffold import LOCAL_ARTIFACTS, Action, Plan, Verb, printable

# Fixed text around `names`, which is each file through `printable`: a `[paths]` value inside the
# path grammar, or the artifact's id.
IGNORED = (
    "git ignores {count} file(s) this run would write or remove, at a place a [paths] value in "
    "stayfixed.toml chose ({names}), so the change would never show in a diff and git could not "
    "give it back; nothing was written. Point that [paths] key at a path git does not ignore, "
    "or take it out to use the preset's place, then run the command again"
)
IGNORED_REMOVING = (
    "git ignores {count} file(s) uninstall would remove or rewrite, at a place a [paths] value "
    "in stayfixed.toml chose ({names}), so what it did there would never show in a diff and git "
    "could not give it back; nothing was removed. Take stayfixed's part out of them by hand, or "
    "take that [paths] key out of stayfixed.toml: uninstall then leaves those files where they "
    "are and lists them"
)
# One refusal for every answer that is not one, a timeout and a `git` that cannot start included:
# what the person can do about each is the same, run it again once git answers. 0.3.1's words.
DECLINED = (
    "git could not say whether the files this run would write or remove are ignored, so nothing "
    "was written; run it again once `git check-ignore` works in this repository"
)


def _preset_places(config: Config) -> Mapping[str, frozenset[str]]:
    """Every place this build could put each artifact under the preset's own `[paths]`.

    The same `project_templates` call every command makes, with `config.paths` replaced by the
    `[defaults.paths]` stayfixed ships for `config.stayfixed.preset`, so fixed names come out as
    themselves and every `[paths]`-built target as the preset puts it. A target outside what this
    answers for its id was chosen by a `[paths]` value in `stayfixed.toml`.

    Provenance: the defaults are this build's shipped preset, the only repository input is which
    preset (`load_preset` accepts none this build does not ship), and `could_write` is built by
    this build's code. `project_templates` touches no disk for a target, so nothing here can
    raise `PathEscape` for a place this configuration never uses.
    """
    defaults = preset_defaults(config.project.name, preset=config.stayfixed.preset).paths
    placed = replace(config, paths=defaults)
    prepared = project_templates(
        placed, resolution=Resolution(None, True), document="", adopted=True
    )
    return prepared.could_write


def refuse_ignored(root: Path, config: Config, *plans: Plan, removing: bool = False) -> None:
    """Refuse when git ignores an existing file a write or removal in `plans` targets at a place
    a `[paths]` value chose, or cannot say whether it does inside a work tree; `removing` picks
    `uninstall`'s remedy."""
    existing = [
        action
        for planned in plans
        for action in planned.actions
        if action.verb is not Verb.SKIP_MODIFIED
        and not action.target.startswith(f"{LOCAL_ARTIFACTS}/")
        and os.path.lexists(root / action.target)
    ]
    if not existing:
        return
    places = _preset_places(config)
    chosen: dict[str, Action] = {}
    for action in existing:
        # That artifact's own preset places: any id's would let `[paths] roadmap =
        # "docs/roadmap-history.md"`, with `roadmap_history` moved elsewhere, pass as
        # `roadmap-history`'s place, and a forged `roadmap` record overwrite an ignored file whose
        # bytes stayfixed wrote. (A value naming a file another artifact is still built to write,
        # such as `CLAUDE.md`, never reaches here: `templates.Owners` refuses it.)
        # Exact, not `fsops.path_key`: this is an exemption, and a case variant of a preset place
        # is a value a `[paths]` key chose, so it stays subject to the guard.
        if action.target not in places.get(action.artifact_id, frozenset()):
            chosen.setdefault(action.target, action)
    if not chosen:
        return
    # `--stdin -z`: the paths go in NUL-separated and never as arguments, so none is read as an
    # option, and come back unquoted, so the answer compares with what was asked.
    code, out = git_run(root, "check-ignore", "--stdin", "-z", stdin="\0".join(sorted(chosen)))
    if code == 1:
        return
    if code == 0:
        ignored = sorted({name for name in out.split("\0") if name} & set(chosen))
        if ignored:
            names = ", ".join(sorted({printable(chosen[target]) for target in ignored}))
            text = IGNORED_REMOVING if removing else IGNORED
            raise Refusal(text.format(count=len(ignored), names=names))
        return
    if in_work_tree(root):
        raise Refusal(DECLINED)

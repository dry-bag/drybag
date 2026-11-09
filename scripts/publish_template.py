#!/usr/bin/env python3
"""Publish the overlay template repository from the owner's checkout.

    uv run python scripts/publish_template.py --owner OWNER [--name NAME] [--yes]

Render `templates/overlay/` into a scratch directory, strip the scaffold ledger (a repository
generated from a template carries none, and publishing one would make every generated overlay
read as hand-edited to `overlay upgrade`), make sure the repository exists, is public and is
marked as a template, clone it, replace its tree with the render, commit, and — only with
`yes` — push. Everything that leaves this process goes through `Runner`, so a test asserts the
argv and never reaches GitHub. The repository it publishes is the one `drybag setup --overlay
create:<owner>/<name>` generates from when the owner has one. A maintainer's script rather than a
command drybag ships: an owner creates an overlay, and only a publisher publishes the template.

**`yes` gates everything outward-facing**, which is three acts and not one: the repository's
creation, its template flag, and the push. Without it the command renders, asks `gh` what
exists — a read — and reports what it would create, mark and push. That is the dry run; there
is no separate `--dry-run` flag, because a second way to say the same thing is a second thing
to get wrong. The first draft of this ran `gh repo create --public` before the gate, so the
documented dry run created a public repository on the owner's account.

**It runs from the owner's authenticated checkout by design.** The public repository's CI
holds no credential that can write a second repository, so this is not a workflow and never
becomes one. `gh` decides the protocol and carries the token; this module only names the argv.
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

# Before the CLI frame exists, so said here: an interpreter without this repository's `drybag`
# would otherwise end in a traceback.
try:
    import drybag
    from drybag import fsops
    from drybag.cli import JSON_EPILOG, run
    from drybag.errors import Failure, Refusal
    from drybag.jsonobject import json_object
    from drybag.overlay.api import OVERLAY_FILES, TEMPLATE_REPOSITORY, render_template, segment
    from drybag.printed import answered
    from drybag.result import Result
    from drybag.runner import NOT_FOUND, TIMED_OUT, Completed, Runner, subprocess_runner
    from drybag.scaffold import MANIFEST_PATH
except ImportError as exc:
    sys.stderr.write(
        f"scripts/publish_template.py: refused: {exc}; run it with `uv run python "
        "scripts/publish_template.py`, which puts this repository's drybag on the path; "
        "nothing was run\n"
    )
    sys.exit(2)

DESCRIPTION = "The template a drybag private overlay is generated from"
# The branch a repository this command just created has: `gh repo create` with no push leaves
# no branch to read, so there is nothing to ask and the platform's own default is what a first
# push names. An existing repository answers for itself through `Existing.default_branch`.
DEFAULT_BRANCH = "main"


@dataclass(frozen=True)
class Published:
    repository: str
    changed: tuple[str, ...]
    pushed: bool
    notes: tuple[str, ...]


@dataclass(frozen=True)
class Existing:
    """What `gh repo view` says about the named repository, before anything is decided.

    Read once and passed to both the dry-run report and the ensure step, so the two cannot
    disagree about what is there — and so the read happens above the gate while every write
    happens below it.
    """

    exists: bool
    is_template: bool
    visibility: str
    default_branch: str


def _gh(runner: Runner, argv: list[str], cwd: Path) -> Completed:
    done = runner.launch(["gh", *argv], cwd)
    if done.code in (NOT_FOUND, TIMED_OUT):
        raise Failure(
            f"`gh {' '.join(argv[:2])} …` could not be run ({answered(done)}); install and "
            f"authenticate gh"
        )
    return done


def _git(runner: Runner, argv: list[str], cwd: Path) -> Completed:
    """`_gh`'s twin for the `git` half, and it exists because the `git` half had no guard.

    The four `git` calls in this module went through the runner directly, and two of them —
    `add -A` and `status --porcelain` — had their exit codes read by nothing. A `git` that is
    absent, hung, blocked by an `index.lock` another process left, or failed by a
    `core.hooksPath` pre-commit hook returns an empty `stdout`, so `changed` came out empty and
    the publisher reported *"already carries this drybag's template; nothing to push"* and
    exited 0. Four different causes, one message, none of them named, and the operator told the
    published template is current when nothing was examined and nothing was pushed.

    `NOT_FOUND` and `TIMED_OUT` are the two the seam invents rather than `git` reporting, which
    is why they get their own sentence: neither is an answer from `git` at all.
    """
    done = runner.launch(["git", *argv], cwd)
    if done.code in (NOT_FOUND, TIMED_OUT):
        raise Failure(
            f"`git {' '.join(argv[2:4])} …` could not be run ({answered(done)}); this command "
            f"needs git on PATH to publish"
        )
    return done


# What `gh` says when the repository really is not there, in the two spellings it uses: the
# GraphQL resolution failure for `repo view`, and the REST 404 for anything that falls through
# to `gh api`. Matched on `gh`'s own stderr rather than on an exit code, because the exit code
# is 1 for every failure this command can meet.
_NOT_FOUND_REMOTELY = re.compile(
    r"could not resolve to a repository|http 404|not found", re.IGNORECASE
)


def _inspect_repository(runner: Runner, slug: str, cwd: Path) -> Existing:
    """Ask GitHub what is there. A read, and the only outward-facing call the gate does not
    cover — because reporting what `--yes` would do requires knowing what exists."""
    view = _gh(
        runner, ["repo", "view", slug, "--json", "isTemplate,visibility,defaultBranchRef"], cwd
    )
    if view.code != 0:
        # **Not every non-zero answer is "it is not there."** `gh repo view` exits non-zero
        # for a repository that is absent, and equally for an unauthenticated `gh`, a rate
        # limit and a network failure. Reading all of them as `exists=False` made the dry run
        # offer to *create* a repository that exists and is private — the opposite of the
        # truth, and precisely the case `_not_public` exists to refuse — after which `--yes`
        # failed at `gh repo create` with GitHub's "name already exists", so the error the
        # operator finally saw named the wrong cause.
        #
        # The distinguishing evidence is `gh`'s own not-found sentence. Anything else is a
        # question this command could not ask, and the gate never reports on one of those.
        #
        # **One case this cannot separate, said plainly rather than left implied.** GitHub
        # answers 404 for a private repository the token may not see, deliberately, so
        # "not there" and "there and not yours" are the same answer over the wire. An owner
        # publishing under an account `gh` is authenticated as does not meet it; an owner who
        # authenticated as somebody else does, and for them `--yes` still stops at
        # `gh repo create`. Distinguishing it would take a credential this command should not
        # want.
        if not _NOT_FOUND_REMOTELY.search(answered(view)):
            raise Failure(
                f"`gh repo view {slug}` exited {view.code} ({answered(view)}), so whether "
                f"{slug} exists is not known; authenticate gh, or retry"
            )
        return Existing(False, False, "", DEFAULT_BRANCH)
    # Through `jsonobject`, the one reader of a JSON object: valid JSON past the parser, its
    # depth bound or the integers it converts is one more answer this cannot read.
    document = json_object(
        view.stdout or "{}",
        f"what `gh repo view {slug}` answered",
        error=Failure,
        limit=lambda _: Failure(
            f"`gh repo view {slug}` answered with JSON past what this reader follows"
        ),
        shape=lambda _: Failure(f"`gh repo view {slug}` answered with JSON that is not an object"),
    )
    branch = document.get("defaultBranchRef")
    named = branch.get("name") if isinstance(branch, dict) else None
    return Existing(
        True,
        bool(document.get("isTemplate")),
        str(document.get("visibility") or ""),
        str(named or DEFAULT_BRANCH),
    )


def _not_public(slug: str, visibility: str) -> str:
    return (
        f"{slug} exists and is not public ({visibility.lower() or 'visibility unknown'}); a "
        f"template is generated from by other accounts only when it is public, and a "
        f"repository under this name that somebody made private is not one this command may "
        f"flip a flag on — publish under a different --name, or make that repository public "
        f"yourself first"
    )


def _dry_run_notes(existing: Existing, slug: str) -> list[str]:
    """What `--yes` would do, said before any of it is done."""
    if not existing.exists:
        return [f"would create {slug}, public, and mark it as a template"]
    if existing.visibility.upper() != "PUBLIC":
        return [f"{_not_public(slug, existing.visibility)} — so --yes would refuse here"]
    if not existing.is_template:
        return [f"would mark {slug} as a template repository"]
    return []


def _ensure_repository(
    runner: Runner, slug: str, cwd: Path, existing: Existing
) -> tuple[list[str], str]:
    """Create it public, or mark an existing public one — and refuse one that is not public.

    Returns the notes and the branch a push should name.
    """
    notes: list[str] = []
    if not existing.exists:
        created = _gh(
            runner, ["repo", "create", slug, "--public", "--description", DESCRIPTION], cwd
        )
        if created.code != 0:
            raise Failure(f"`gh repo create {slug}` exited {created.code} ({answered(created)})")
        notes.append(f"created {slug}, public")
        is_template, default_branch = False, DEFAULT_BRANCH
    else:
        if existing.visibility.upper() != "PUBLIC":
            raise Refusal(_not_public(slug, existing.visibility))
        is_template, default_branch = existing.is_template, existing.default_branch
    if not is_template:
        marked = _gh(runner, ["repo", "edit", slug, "--template"], cwd)
        if marked.code != 0:
            raise Failure(
                f"`gh repo edit {slug} --template` exited {marked.code} ({answered(marked)})"
            )
        notes.append(f"marked {slug} as a template repository")
    return notes, default_branch


def _render_tree(rendered: Path) -> tuple[str, ...]:
    """The shipped files the render actually left, in `OVERLAY_FILES` order."""
    return tuple(relative for relative in OVERLAY_FILES if fsops.is_file(rendered / relative))


def _replace_tree(clone: Path, rendered: Path, written: tuple[str, ...]) -> None:
    """Every tracked file out, every file the render left in — through the contained walk.

    **`written` and not `OVERLAY_FILES`, because the dry run already answered this question.**
    `_render_tree` reports the shipped files the render actually left, and this loop used to
    read every `OVERLAY_FILES` entry unconditionally — so a render missing one file made the
    dry run under-report by one and made the `--yes` run raise `FileNotFoundError` out of a
    library module, which `cli.run` renders as `internal error`, exit 2. It is unreachable
    today (`tests/overlay/test_template.py` holds `OVERLAY_FILES` against the template tree
    both ways), and two functions answering one question two ways is the shape that stops
    being unreachable without anyone deciding it should.

    **The containment anchor is `clone`, and this process made it.** It is a directory under
    the `TemporaryDirectory` opened two frames up, named by this module and cloned into by
    `gh`; no argument, no configuration file and no repository chooses it, which is what makes
    "refuse anything outside it" a rule the party being contained cannot move. `.git` is the
    one thing left standing, because the clone's history is what the push carries.
    """
    for path in sorted(clone.rglob("*"), reverse=True):
        if ".git" in path.relative_to(clone).parts:
            continue
        relative = str(path.relative_to(clone))
        if fsops.is_file(path):
            fsops.remove_within(clone, relative)
        elif fsops.is_dir(path) and not any(path.iterdir()):
            fsops.rmdir_within(clone, relative)
    for relative in written:
        fsops.write_within(clone, relative, (rendered / relative).read_text(encoding="utf-8"))


def publish_template(
    owner: str, *, name: str = TEMPLATE_REPOSITORY, yes: bool, runner: Runner
) -> Published:
    """Render the shipped overlay tree and publish it as `<owner>/<name>`."""
    # Folded before it is validated, exactly as `overlay.api.target_root` folds it and for the
    # same reason: `SEGMENT` has a lowercase leading class and a mixed-case GitHub login is
    # ordinary.
    account = segment("owner", owner.strip().lower())
    segment("name", name)
    slug = f"{account}/{name}"
    with tempfile.TemporaryDirectory(prefix="drybag-publish-") as scratch_name:
        scratch = Path(scratch_name)
        rendered = render_template(scratch, "rendered")
        # The ledger is the scaffold engine's record of what the render wrote here. A repository
        # generated from a template carries none, so publishing one would make every generated
        # overlay read as hand-edited to `overlay upgrade` and never be refreshed again.
        #
        # `_replace_tree` writes only the files the render left, so today the ledger could not
        # reach the clone even unstripped — this is the second of two independent mechanisms,
        # and it is the one that survives a `_replace_tree` which ever copies the render whole.
        # It is held by a test over the RENDER and not over the pushed tree, because an
        # assertion over the pushed tree is satisfied by the whitelist alone and says nothing
        # about this.
        fsops.remove_within(rendered, str(MANIFEST_PATH))
        fsops.rmdir_within(rendered, str(MANIFEST_PATH.parent))
        # Nothing outward-facing before the gate. Without `yes` the repository is only ASKED
        # about: what would be created or marked is reported, never done — a dry run that
        # created a public repository on the owner's account was the first draft's defect.
        existing = _inspect_repository(runner, slug, scratch)
        written = _render_tree(rendered)
        if not yes:
            notes = _dry_run_notes(existing, slug)
            if existing.exists and existing.visibility.upper() != "PUBLIC":
                return Published(slug, written, False, tuple(notes))
            notes.append(
                f"would push {len(written)} file(s) to {slug}; re-run with --yes to publish"
            )
            return Published(slug, written, False, tuple(notes))
        notes, default_branch = _ensure_repository(runner, slug, scratch, existing)
        # `gh repo clone`, not `git clone git@…`: it uses whichever protocol `gh` is
        # authenticated over, which is the premise the whole command rests on. A full clone,
        # not `--depth 1`: a shallow graft is not a history anyone wants pushed.
        cloned = runner.launch(["gh", "repo", "clone", slug, "clone"], scratch)
        clone = scratch / "clone"
        if cloned.code != 0 or not fsops.is_dir(clone):
            raise Failure(f"`gh repo clone {slug}` exited {cloned.code} ({answered(cloned)})")
        _replace_tree(clone, rendered, written)
        added = _git(runner, ["-C", str(clone), "add", "-A"], clone)
        if added.code != 0:
            raise Failure(f"`git add -A` in the clone exited {added.code} ({answered(added)})")
        status = _git(runner, ["-C", str(clone), "status", "--porcelain"], clone)
        # Read before the emptiness of `stdout` is interpreted. An empty listing means "the
        # published tree is already this drybag's" only when the question was actually
        # answered; a non-zero `git status` produces the same empty string and means nothing of
        # the kind.
        if status.code != 0:
            raise Failure(
                f"`git status` in the clone exited {status.code} ({answered(status)}), so "
                f"whether {slug} already carries this template is not known"
            )
        changed = tuple(line[3:] for line in status.stdout.splitlines() if line.strip())
        if not changed:
            notes.append(f"{slug} already carries this drybag's template; nothing to push")
            return Published(slug, (), False, tuple(notes))
        message = f"drybag overlay template {drybag.__version__}"
        committed = _git(runner, ["-C", str(clone), "commit", "-q", "-m", message], clone)
        if committed.code != 0:
            raise Failure(
                f"committing the template exited {committed.code} ({answered(committed)})"
            )
        # `HEAD:refs/heads/<default>`: a freshly created repository has no branch to clone,
        # so a bare `push origin HEAD` would push whatever `init.defaultBranch` says.
        pushed = _git(
            runner, ["-C", str(clone), "push", "origin", f"HEAD:refs/heads/{default_branch}"], clone
        )
        if pushed.code != 0:
            raise Failure(f"`git push` to {slug} exited {pushed.code} ({answered(pushed)})")
        notes.append(f"pushed {len(changed)} changed file(s) to {slug} as {message!r}")
    return Published(slug, changed, True, tuple(notes))


def run_publish(args: argparse.Namespace) -> Result:
    published = publish_template(
        args.owner, name=args.name, yes=args.yes, runner=subprocess_runner()
    )
    data = {
        "repository": published.repository,
        "changed": list(published.changed),
        "pushed": published.pushed,
        "notes": list(published.notes),
    }
    return Result(f"{published.repository}: {'; '.join(published.notes)}", data)


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(
        prog="scripts/publish_template.py",
        description="Publish the overlay template repository from this checkout.",
        epilog=JSON_EPILOG,
    )
    top.add_argument("--owner", required=True, help="the account to publish the template to")
    top.add_argument(
        "--name", default=TEMPLATE_REPOSITORY, help="the repository name (default: %(default)s)"
    )
    # The gate, and it is a parameter rather than a step in a procedure: in an agent harness a
    # flag a model can type is not a control, so the three outward-facing acts — creating the
    # repository, marking it a template, pushing — all sit behind this one value.
    top.add_argument(
        "--yes",
        action="store_true",
        help="create, mark and push; without it nothing outward-facing happens — the script "
        "renders, asks gh what exists, and reports what it would do",
    )
    top.set_defaults(func=run_publish)
    return top


def main(argv: list[str] | None = None) -> int:
    return run(sys.argv[1:] if argv is None else argv, parser=parser())


if __name__ == "__main__":
    sys.exit(main())

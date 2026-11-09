"""`scripts/publish_template.py`: render, strip the ledger, push one commit from the owner's
checkout, and never without `--yes`."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from drybag import jsonobject
from drybag.errors import Failure, Refusal
from drybag.overlay.api import OVERLAY_FILES, TEMPLATE_REPOSITORY
from drybag.runner import NOT_FOUND, Completed
from drybag.scaffold import MANIFEST_PATH
from tests.parserlimits import DEEPER_THAN_FOUR, LONG_NUMBER, NESTED
from tests.scriptload import publish_template as script

publish_template = script().publish_template


@dataclass
class _GitHub:
    """`gh` and `git` as the publisher sees them: recorded, and the clone materialised.

    `git clone` has to leave a directory behind, or the publisher has nothing to write into;
    the stub creates it with one stale file, which the publisher must remove. `exists` says
    whether `gh repo view` answers.

    Not `tests.runners.Recorder`, because it answers a different question. That one replays a
    script of answers; this one models a repository on GitHub — whether it exists, whether it is
    a template, its visibility — and derives `gh repo view`'s JSON from that state, materialises
    the clone the publisher then writes into, and snapshots the render at clone time. The cases
    below vary GitHub's state, or override one call in a subclass, and a script would have to
    restate the whole model in every one of them.
    """

    exists: bool = True
    is_template: bool = True
    visibility: str = "PUBLIC"
    calls: list[tuple[list[str], Path]] = field(default_factory=list)
    pushed_tree: set[str] = field(default_factory=set)
    # The render, snapshotted where the clone is made beside it. The scratch directory is gone
    # when `publish_template` returns, and the render is the only place the scaffold ledger's
    # removal is observable at all — see the test that says so.
    rendered_tree: set[str] = field(default_factory=set)

    def launch(self, argv: list[str], cwd: Path) -> Completed:
        self.calls.append((argv, cwd))
        if argv[:3] == ["gh", "repo", "view"]:
            if not self.exists:
                return Completed(1, "", "GraphQL: Could not resolve to a Repository")
            body = '{"isTemplate": %s, "visibility": "%s", "defaultBranchRef": {"name": "main"}}'
            marked = "true" if self.is_template else "false"
            return Completed(0, body % (marked, self.visibility), "")
        if argv[:3] == ["gh", "repo", "clone"]:
            rendered = cwd / "rendered"
            self.rendered_tree = {
                str(p.relative_to(rendered)) for p in rendered.rglob("*") if p.is_file()
            }
            target = cwd / argv[-1]
            (target / ".git").mkdir(parents=True)
            (target / "stale.md").write_text("old\n", encoding="utf-8")
            # A nested stale file as well as a loose one, because the two exercise different
            # halves of `_replace_tree`: the file walk removes both, and only the directory
            # walk takes `old/deep/` away afterwards.
            (target / "old" / "deep").mkdir(parents=True)
            (target / "old" / "deep" / "note.md").write_text("old\n", encoding="utf-8")
            return Completed(0, "", "")
        if argv[:2] == ["git", "-C"] and "status" in argv:
            return Completed(0, " M README.md\n?? hooks/hooks.json\n D stale.md\n", "")
        if argv[:2] == ["git", "-C"] and "push" in argv:
            clone = Path(argv[2])
            self.pushed_tree = {
                str(p.relative_to(clone))
                for p in clone.rglob("*")
                if p.is_file() and ".git" not in p.parts
            }
        return Completed(0, "", "")


def _argv(stub: _GitHub) -> list[list[str]]:
    return [argv for argv, _ in stub.calls]


def test_without_yes_nothing_is_pushed_and_the_push_is_named(tmp_path: Path) -> None:
    # `yes` gates everything outward-facing, which is THREE acts and not one: the
    # repository's creation, its template flag, and the push (`publish.py`'s module
    # docstring). This case holds the third; the case below holds the first two, and it
    # exists because the first draft ran `gh repo create --public` before the gate. The name
    # and comment this carried said "the one outward-facing act" and "the push is what it
    # guards" — the design the gate replaced, in the file a reader opens to learn what
    # `--yes` covers, and wrong in the unsafe direction. The gate is still a parameter and
    # not a typed flag; that half was right.
    # Mutation (declared): push regardless of `yes` -> `pushed` is True and reddens.
    stub = _GitHub()
    result = publish_template("Owner", yes=False, runner=stub)
    assert result.pushed is False
    assert not [a for a in _argv(stub) if "push" in a]
    assert any("re-run with --yes" in note for note in result.notes)
    assert result.repository == f"owner/{TEMPLATE_REPOSITORY}"


def test_without_yes_no_repository_is_created_or_marked(tmp_path: Path) -> None:
    # The first draft ran `gh repo create --public` and `gh repo edit --template` BEFORE the
    # `yes` gate, so the documented dry run created a public repository on the owner's account.
    # Mutation (declared): move `_ensure_repository` above the gate -> both assertions redden.
    stub = _GitHub(exists=False)
    result = publish_template("owner", yes=False, runner=stub)
    argv = _argv(stub)
    assert not [a for a in argv if a[:3] == ["gh", "repo", "create"]]
    assert not [a for a in argv if a[:3] == ["gh", "repo", "edit"]]
    assert any("would create" in note for note in result.notes)


def test_a_dry_run_against_a_repository_that_is_not_public_promises_no_push(
    tmp_path: Path,
) -> None:
    # The dry run reports what `--yes` would do, so it must not promise a push that `--yes`
    # would refuse. The private case is the one where those two answers differ.
    stub = _GitHub(exists=True, is_template=False, visibility="PRIVATE")
    result = publish_template("owner", yes=False, runner=stub)
    assert result.pushed is False
    assert any("would refuse" in note for note in result.notes)
    assert not [note for note in result.notes if "re-run with --yes" in note]
    assert not [a for a in _argv(stub) if a[:3] == ["gh", "repo", "edit"]]


def test_an_existing_repository_that_is_not_public_is_refused_not_marked(tmp_path: Path) -> None:
    stub = _GitHub(exists=True, is_template=False, visibility="PRIVATE")
    with pytest.raises(Refusal, match="not public"):
        publish_template("owner", yes=True, runner=stub)
    assert not [a for a in _argv(stub) if a[:3] == ["gh", "repo", "edit"]]


def test_with_yes_the_rendered_tree_is_committed_and_pushed_without_the_ledger(
    tmp_path: Path,
) -> None:
    # The scratch tree is gone when `publish_template` returns, so the stub snapshots the
    # clone at push time (`_GitHub.pushed_tree`) and the assertions are over the snapshot.
    stub = _GitHub()
    result = publish_template("owner", yes=True, runner=stub)
    assert result.pushed is True
    written = stub.pushed_tree
    assert written == set(OVERLAY_FILES), written ^ set(OVERLAY_FILES)
    # This one guards `_replace_tree`'s whitelist and NOT the ledger strip: that function
    # writes only `OVERLAY_FILES`, so the ledger cannot reach the clone whether it was
    # stripped or not. Measured — with the strip deleted, all 74 cases in this directory still
    # passed. The strip has a case of its own below, over the render.
    assert str(MANIFEST_PATH) not in written
    assert "stale.md" not in written
    assert not [name for name in written if name.startswith("old/")]
    push = next(a for a in _argv(stub) if "push" in a)
    assert push[-1] == "HEAD:refs/heads/main"
    commit = next(a for a in _argv(stub) if "commit" in a)
    assert any(m.startswith("drybag overlay template ") for m in commit)


def test_a_missing_repository_is_created_public_and_marked_as_a_template(tmp_path: Path) -> None:
    # The template is the PUBLIC half of the pair, and it is marked `is_template` so an owner
    # can generate a private overlay from it. Mutation (declared): drop `--public` -> reddens.
    stub = _GitHub(exists=False)
    publish_template("owner", yes=True, runner=stub)
    argv = _argv(stub)
    assert [
        "gh",
        "repo",
        "create",
        f"owner/{TEMPLATE_REPOSITORY}",
        "--public",
        "--description",
        "The template a drybag private overlay is generated from",
    ] in argv
    assert ["gh", "repo", "edit", f"owner/{TEMPLATE_REPOSITORY}", "--template"] in argv


def test_an_existing_repository_not_yet_a_template_is_marked_and_not_recreated(
    tmp_path: Path,
) -> None:
    stub = _GitHub(exists=True, is_template=False)
    publish_template("owner", yes=True, runner=stub)
    argv = _argv(stub)
    assert not [a for a in argv if a[:3] == ["gh", "repo", "create"]]
    assert ["gh", "repo", "edit", f"owner/{TEMPLATE_REPOSITORY}", "--template"] in argv


def test_a_gh_that_cannot_run_is_a_failure_naming_it(tmp_path: Path) -> None:
    class _NoGh(_GitHub):
        def launch(self, argv: list[str], cwd: Path) -> Completed:
            if argv[0] == "gh":
                return Completed(NOT_FOUND, "", "gh could not be run")
            return super().launch(argv, cwd)

    with pytest.raises(Failure, match="gh repo view"):
        publish_template("owner", yes=True, runner=_NoGh())


def test_a_gh_that_cannot_answer_is_never_read_as_a_repository_that_is_absent() -> None:
    # `gh repo view` exits 1 for a repository that is not there, and equally for an
    # unauthenticated `gh`, a rate limit, a network failure and a repository the token cannot
    # see. All four read as `exists=False`, so the dry run against an account that already owns
    # a PRIVATE `drybag-overlay-template` printed
    # `would create owner/drybag-overlay-template, public, and mark it as a template` —
    # the opposite of the truth, and exactly the case `_not_public` exists to refuse.
    # Mutation (declared): the not-found test is dropped and every non-zero answer is absence
    # again -> the "would create" note comes back.
    class _LoggedOut(_GitHub):
        def launch(self, argv: list[str], cwd: Path) -> Completed:
            if argv[:3] == ["gh", "repo", "view"]:
                self.calls.append((argv, cwd))
                return Completed(1, "", "gh: To use GitHub CLI in a GitHub Actions workflow…")
            return super().launch(argv, cwd)

    stub = _LoggedOut()
    with pytest.raises(Failure, match="is not known") as raised:
        publish_template("owner", yes=False, runner=stub)
    assert "authenticate gh" in str(raised.value)
    assert "would create" not in str(raised.value)


def test_a_repository_gh_really_cannot_find_is_still_reported_as_absent() -> None:
    # The other side of the same test, and the reason it is a pair: a guard that refused every
    # non-zero answer would break the one case this command exists for, the first publish. The
    # stub's not-found stderr is `gh`'s own sentence.
    stub = _GitHub(exists=False)
    result = publish_template("owner", yes=False, runner=stub)
    assert any("would create" in note for note in result.notes), result.notes


def test_a_git_that_cannot_run_is_a_failure_and_not_a_report_that_nothing_changed() -> None:
    # The `gh` half had this guard and the `git` half did not. Measured before the fix, with
    # every `git` argv answering `Completed(NOT_FOUND, "", …)` and `gh` answering normally:
    #
    #   pushed : False
    #   changed: ()
    #   note   : someowner/drybag-overlay-template already carries this drybag's
    #            template; nothing to push
    #
    # exit 0, and the operator told the published template is current when nothing was
    # examined and nothing was pushed. The same output came from `git` timing out, from an
    # `index.lock` another process left, and from a `core.hooksPath` hook failing `git add`.
    # Mutation (declared): `_git` stops raising on the two sentinels -> the note comes back.
    class _NoGit(_GitHub):
        def launch(self, argv: list[str], cwd: Path) -> Completed:
            if argv[0] == "git":
                self.calls.append((argv, cwd))
                return Completed(NOT_FOUND, "", "git could not be run: [Errno 2]")
            return super().launch(argv, cwd)

    stub = _NoGit()
    with pytest.raises(Failure, match="needs git on PATH") as raised:
        publish_template("someowner", yes=True, runner=stub)
    # The specific sentence, and not merely "a Failure": the whole defect is that a `git`
    # nobody could run read as an answer, so a message that does not name `git` would be the
    # same silence one level up.
    assert "could not be run" in str(raised.value)
    assert "nothing to push" not in str(raised.value)


def test_a_git_status_that_fails_is_never_read_as_an_unchanged_template() -> None:
    # The other half, and the one no sentinel covers: `git` runs and answers non-zero — a
    # broken index, a repository `git status` refuses — with an empty stdout that is
    # byte-identical to "nothing changed". `add -A` succeeds here, so this is squarely the
    # emptiness-versus-exit-code reading and not the launch guard above.
    # Mutation (declared): `status.code` stops being read -> "nothing to push" comes back.
    class _BrokenStatus(_GitHub):
        def launch(self, argv: list[str], cwd: Path) -> Completed:
            if argv[:2] == ["git", "-C"] and "status" in argv:
                self.calls.append((argv, cwd))
                return Completed(128, "", "fatal: not a git repository")
            return super().launch(argv, cwd)

    stub = _BrokenStatus()
    with pytest.raises(Failure, match="is not known") as raised:
        publish_template("someowner", yes=True, runner=stub)
    assert "exited 128" in str(raised.value)
    assert not [a for a in _argv(stub) if "commit" in a or "push" in a]


def test_a_dry_run_against_a_public_repository_that_is_not_a_template_says_it_would_mark_it(
    tmp_path: Path,
) -> None:
    # The third arm of the dry-run report, and the one an owner meets on a second release
    # against a repository they created by hand. Without this the arm is written and unasserted.
    stub = _GitHub(exists=True, is_template=False, visibility="PUBLIC")
    result = publish_template("owner", yes=False, runner=stub)
    assert any("would mark" in note for note in result.notes)
    assert any("re-run with --yes" in note for note in result.notes)
    assert not [a for a in _argv(stub) if a[:3] == ["gh", "repo", "edit"]]


def test_a_template_that_is_already_current_is_not_committed_or_pushed(tmp_path: Path) -> None:
    # Idempotence, which is what makes "run it at every release" safe: `git status` reporting
    # nothing means the published tree is already this drybag's, and an empty commit pushed
    # over it would be a release note for a release that changed nothing.
    class _Unchanged(_GitHub):
        def launch(self, argv: list[str], cwd: Path) -> Completed:
            if argv[:2] == ["git", "-C"] and "status" in argv:
                self.calls.append((argv, cwd))
                return Completed(0, "", "")
            return super().launch(argv, cwd)

    stub = _Unchanged()
    result = publish_template("owner", yes=True, runner=stub)
    assert result.pushed is False
    assert result.changed == ()
    assert any("nothing to push" in note for note in result.notes)
    assert not [a for a in _argv(stub) if "commit" in a or "push" in a]


def test_a_push_that_is_declined_is_a_failure_naming_the_repository(tmp_path: Path) -> None:
    # `gh` that could not be launched at all is the case above; this is the other one, and the
    # states have different remedies. A push refused by a ruleset or a lost credential must not
    # read as a publish that worked.
    class _RefusedPush(_GitHub):
        def launch(self, argv: list[str], cwd: Path) -> Completed:
            recorded = super().launch(argv, cwd)
            if argv[:2] == ["git", "-C"] and "push" in argv:
                return Completed(1, "", "remote: refused by a ruleset")
            return recorded

    with pytest.raises(Failure, match="refused by a ruleset") as failed:
        publish_template("owner", yes=True, runner=_RefusedPush())
    # The name promises the repository, and `refused by a ruleset` is the STUB's own stderr:
    # it is quoted back whatever the message says about which repository was pushed to, so
    # the assertion above held with the slug dropped from the sentence. The slug is the half
    # only this code produces.
    assert f"owner/{TEMPLATE_REPOSITORY}" in str(failed.value)


def test_the_render_the_publisher_clones_beside_carries_no_scaffold_ledger(tmp_path: Path) -> None:
    # `scaffold.apply` writes `.drybag/manifest.json` into every local
    # render, and a repository generated from a template carries none — publishing one would
    # make every generated overlay read as hand-edited to `overlay upgrade` and never be
    # refreshed again. The first assertion written for this was over the PUSHED tree, which
    # `_replace_tree`'s whitelist keeps clean on its own: deleting the strip left every case
    # in this file green. The strip is observable one step earlier, in the render, and the
    # stub snapshots it at clone time because the scratch directory is gone by the time
    # `publish_template` returns. Mutation (declared): drop the strip -> this reddens.
    stub = _GitHub()
    publish_template("owner", yes=True, runner=stub)
    assert stub.rendered_tree, "the stub never saw the render, so this asserts nothing"
    assert str(MANIFEST_PATH) not in stub.rendered_tree
    assert stub.rendered_tree == set(OVERLAY_FILES), stub.rendered_tree ^ set(OVERLAY_FILES)


def test_what_gh_prints_cannot_drive_a_terminal() -> None:
    # `gh`'s answer was quoted raw in the failure: a line break followed by `::error::` is a
    # workflow command in a CI log, and an escape sequence drives a terminal.
    #
    # Mutation: `mutations/`'s "a subprocess's answer is quoted raw".
    class _Hostile(_GitHub):
        def launch(self, argv: list[str], cwd: Path) -> Completed:
            if argv[:3] == ["gh", "repo", "view"]:
                self.calls.append((argv, cwd))
                return Completed(1, "", "HTTP 500\n::error::forged\x1b[2J")
            return super().launch(argv, cwd)

    with pytest.raises(Failure) as raised:
        publish_template("owner", yes=False, runner=_Hostile())
    message = str(raised.value)
    assert "forged" in message
    assert "\n::error::" not in message and "\x1b" not in message


@pytest.mark.parametrize(
    "answer", [NESTED, f'{{"isTemplate": {LONG_NUMBER}}}'], ids=["nested", "long"]
)
def test_a_repository_view_past_the_parser_is_a_failure_and_never_an_internal_error(
    answer: str,
) -> None:
    # Valid JSON that `json.loads` answers with `RecursionError` or a plain `ValueError`, neither
    # of them the `JSONDecodeError` this caught: an answer this cannot read ended the command as
    # an internal error rather than as the failure an answer that is not JSON is. Mutation
    # (declared): the arm for valid JSON past the parser removed -> it escapes.
    class _Deep(_GitHub):
        def launch(self, argv: list[str], cwd: Path) -> Completed:
            if argv[:3] == ["gh", "repo", "view"]:
                return Completed(0, answer, "")
            return super().launch(argv, cwd)

    with pytest.raises(Failure, match="past what this reader follows"):
        publish_template("owner", yes=False, runner=_Deep())


def test_a_repository_view_past_the_depth_bound_is_a_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # `gh`'s answer goes through the one JSON object reader, so its depth bound holds here too.
    # Mutation (declared): `mutations/`'s "publish-template parses the repository view with a bare
    # json.loads".
    monkeypatch.setattr(jsonobject, "DEPTH_CAP", 4)

    class _Deep(_GitHub):
        def launch(self, argv: list[str], cwd: Path) -> Completed:
            if argv[:3] == ["gh", "repo", "view"]:
                return Completed(0, DEEPER_THAN_FOUR, "")
            return super().launch(argv, cwd)

    with pytest.raises(Failure, match="past what this reader follows"):
        publish_template("owner", yes=False, runner=_Deep())

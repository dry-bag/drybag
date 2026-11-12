from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import NoReturn

import pytest

from drybag import jsonobject
from drybag.errors import Failure, Refusal
from drybag.overlay.api import finish, generate, render
from drybag.overlay.create import RETRY_WAIT_SECONDS, UNRECORDED, _is_template
from drybag.overlay.layout import IDENTITY_RECORD
from drybag.printed import quoted
from drybag.runner import TIMED_OUT, Completed
from tests.parserlimits import LONG_NUMBER, NESTED
from tests.runners import Recorder

# What `gh repo view <slug> --json isTemplate` really prints, measured against gh 2.101.0: a
# template answers `{"isTemplate":true}` with exit 0; a repository that is not one answers
# `{"isTemplate":false}`; a repository that does not exist (or that this token cannot see) exits 1
# with GraphQL's "Could not resolve to a Repository" on stderr; a bad token exits 1 with an HTTP
# 401 line. Exit 1 alone therefore cannot tell "not found" from "not authenticated", and the
# stderr is the only thing that can.
A_TEMPLATE = Completed(0, '{"isTemplate":true}\n', "")
NOT_A_TEMPLATE = Completed(0, '{"isTemplate":false}\n', "")
NO_SUCH_REPOSITORY = Completed(
    1,
    "",
    "GraphQL: Could not resolve to a Repository with the name 'octo/drybag-overlay-template'."
    " (repository)\n",
)
# A repository of the owner's own, published or not: the probe `create` asks before it chooses.
THE_OWNERS_PROBE = "gh repo view octo/drybag-overlay-template"


def _populate(argv: list[str], cwd: Path) -> None:
    """Stand in for a successful template generation: write the probe `create` looks for."""
    if argv[:3] != ["gh", "repo", "create"]:
        return
    target = cwd / argv[3].split("/")[-1]
    target.mkdir(parents=True, exist_ok=True)
    (target / IDENTITY_RECORD).write_text("layout = 1\n", encoding="utf-8")


def _the_create_call(runner: Recorder) -> list[str]:
    """The one `gh repo create` argv a run made; more or fewer is a finding in its own right."""
    made = [argv for argv in runner.calls if argv[:3] == ["gh", "repo", "create"]]
    assert len(made) == 1, runner.calls
    return made[0]


def _template_named(runner: Recorder) -> str:
    argv = _the_create_call(runner)
    return argv[argv.index("--template") + 1]


def test_creating_from_the_template_asks_github_for_a_private_repository(tmp_path: Path) -> None:
    # A template rather than a fork, because a fork's visibility is bound to the
    # upstream network and cannot be made private. The `--private` flag is that decision.
    runner = Recorder(answers={THE_OWNERS_PROBE: A_TEMPLATE}, on_call=_populate)
    generate("octo", "drybag-private", root=tmp_path, runner=runner)
    creating = _the_create_call(runner)
    assert "--private" in creating
    assert "--template" in creating


def test_a_clone_that_raced_generation_is_retried_once_before_failing(tmp_path: Path) -> None:
    # The race did not reproduce in the one measured trial of template generation, and one
    # clean run cannot rule out an asynchronous generation step that sometimes outlasts the
    # clone. The retry is therefore carried on the strength of reasoning, not of a measurement
    # — so it is asserted here rather than left to be discovered by whoever hits it.
    empty = Recorder(answers={THE_OWNERS_PROBE: A_TEMPLATE})
    with pytest.raises(Failure):
        generate("octo", "drybag-private", root=tmp_path, runner=empty)
    # The repository's own name, not the template's: the probe is also a `gh repo view`.
    verbs = [argv[:4] for argv in empty.calls]
    assert ["gh", "repo", "view", "octo/drybag-private"] in verbs, (
        "must distinguish 'not created' from 'raced'"
    )
    assert ["git", "clone", "--", "git@github.com:octo/drybag-private.git"] in verbs


def test_an_existing_overlay_at_the_destination_is_left_alone(tmp_path: Path) -> None:
    # Generating is idempotent: a second run finds the overlay the first one cloned and must not
    # create it again.
    (tmp_path / "drybag-private").mkdir()
    (tmp_path / "drybag-private" / IDENTITY_RECORD).write_text("layout = 1\n", encoding="utf-8")
    runner = Recorder()
    created = generate("octo", "drybag-private", root=tmp_path, runner=runner)
    assert runner.calls == []
    assert "exists" in " ".join(created.notes)


def test_the_local_render_touches_no_network(tmp_path: Path) -> None:
    # The documented fallback when the template repository is unreachable, and the only mode a
    # test may exercise end to end.
    runner = Recorder()
    created = render(tmp_path / "drybag-private", runner=runner)
    # "Touches no network" is a claim about `gh`: the one local call is `git init`, asserted on
    # its own below. It used to read `runner.calls == []`, which was that claim while the render
    # ran nothing at all.
    assert [argv for argv in runner.calls if argv[0] == "gh"] == []
    assert (created.root / IDENTITY_RECORD).is_file()


@pytest.mark.parametrize("name", ["../escape", "a/b", "", "-flag"])
def test_a_name_that_is_not_one_path_segment_is_refused(tmp_path: Path, name: str) -> None:
    # A name is one path segment, because it becomes a directory name and half a remote path.
    # `-flag` is in the list because a configured value shaped like an option never reaches a
    # subprocess in an option's position.
    runner = Recorder()
    with pytest.raises(Refusal):
        generate("octo", name, root=tmp_path, runner=runner)
    assert runner.calls == []


def test_finish_installs_pre_commit_and_says_so_when_it_cannot(tmp_path: Path) -> None:
    # gitleaks runs twice over the overlay, and one of the two is this hook. A missing
    # `pre-commit` is a reported finding, never a traceback — the binary is optional.
    created = render(tmp_path / "drybag-private", runner=Recorder())
    missing = Recorder(answers={"pre-commit": Completed(127, "", "not found")})
    note = finish(created.root, runner=missing)
    # "did not run" and not merely "pre-commit": the success note names the tool too, so the
    # weaker match held on either outcome and this half asserted nothing.
    assert "`pre-commit install` did not run" in note
    assert "installed the commit-time" not in note


def test_the_secret_scan_note_prints_the_overlay_root_quoted(tmp_path: Path) -> None:
    # The note names where to run `pre-commit` by hand, and `setup` prints it: a root reached
    # through a link a clone commits is spelled in the clone's bytes, and an escape sequence in it
    # drove the terminal and a CI runner's log.
    root = tmp_path / "x\x1b]0;owned\x07"
    root.mkdir()
    said = finish(root, runner=Recorder(answers={"pre-commit": Completed(127, "", "not found")}))
    assert "\x1b" not in said and "\x07" not in said, said
    assert quoted(str(root)) in said, said


def test_the_wait_before_the_retry_is_spent_only_on_the_race(tmp_path: Path) -> None:
    # "on the second, wait and retry once": the pause exists for an asynchronous generation step
    # that may still be running, so it is spent only when `gh repo view` names the repository
    # back. Spending it when nothing was created is ten seconds bought with nothing, and it is
    # the branch the retry test above never reaches. Mutation: make the wait unconditional and
    # the second half reddens; drop it entirely and the first half does.
    named: list[float] = []
    answering = Recorder(
        answers={
            "gh": Completed(0, "drybag-private\n", ""),
            THE_OWNERS_PROBE: A_TEMPLATE,
        }
    )
    with pytest.raises(Failure):
        generate(
            "octo",
            "drybag-private",
            root=tmp_path,
            runner=answering,
            wait=named.append,
        )
    assert named == [RETRY_WAIT_SECONDS]

    silent: list[float] = []
    with pytest.raises(Failure):
        generate(
            "octo",
            "drybag-private",
            root=tmp_path,
            runner=Recorder(answers={THE_OWNERS_PROBE: A_TEMPLATE}),
            wait=silent.append,
        )
    assert silent == []


def test_a_render_that_cannot_start_leaves_no_probe_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A render that refused after writing the identity record would leave the one file
    # `generate` reads as "this was already created", so the honest recovery — `create:` —
    # would report "already exists and was left alone" and never create the repository at all.
    # Everything that can refuse therefore runs first. Mutation: move the `plan(...)` call back
    # below `mkdirs_within` and this reddens on the second assertion, with a directory on disk.
    def _unavailable() -> NoReturn:
        raise Failure("this drybag was installed without the template tree")

    monkeypatch.setattr("drybag.overlay.create.templates", _unavailable)
    with pytest.raises(Failure):
        render(tmp_path / "drybag-private", runner=Recorder())
    assert not (tmp_path / "drybag-private").exists()


def test_a_mixed_case_owner_is_folded_before_it_is_judged(tmp_path: Path) -> None:
    # `SEGMENT` has a lowercase leading class and a mixed-case GitHub login is ordinary, so the
    # owner is folded before it is validated: validating the raw value refused `OctoCat` with "is
    # not one path segment" about a value that is one. Mutation: validate `owner` rather than the
    # folded value in `target_root` and this reddens with a `Refusal`.
    remote = tmp_path / "remote"
    remote.mkdir()
    runner = Recorder(
        answers={"gh repo view octocat/drybag-overlay-template": A_TEMPLATE}, on_call=_populate
    )
    generate("OctoCat", "drybag-private", root=remote, runner=runner)
    # And the fold reaches the argv, not just the validator.
    assert "octocat/drybag-private" in _the_create_call(runner)
    assert runner.calls[0][3] == "octocat/drybag-overlay-template", "the probe folds too"


def test_a_gh_that_cannot_be_run_at_creation_is_named_as_the_cause_and_costs_no_more_calls(
    tmp_path: Path,
) -> None:
    # `Completed` has carried `code` and `stderr` since this seam was written and `overlay.create`
    # threw both away: with `gh` absent from `PATH`, the command launched three subprocesses and
    # then exited 1 saying "GitHub did not confirm the repository exists; check `gh auth status`" —
    # a cause that was not the cause, about a binary that was not there. A missing optional binary
    # is a reported finding, and never a misattributed one.
    #
    # The probe is answered here and `gh repo create` is what cannot run (a `gh` removed between
    # the two calls), because the probe has its own arm and its own test below;
    # this is the one that reaches the creation arm.
    #
    # Mutation (`mutations/`'s "create: asks GitHub about a `gh` that could not run"): the
    # `NOT_FOUND` arm becomes `if False:` → a `gh` that never ran is reported as one that exited
    # 127, and the advice to install it goes.
    absent = Recorder(
        answers={
            THE_OWNERS_PROBE: A_TEMPLATE,
            "gh repo create": Completed(127, "", "gh could not be run: [Errno 2] gh"),
        }
    )
    waited: list[float] = []
    with pytest.raises(Failure) as failed:
        generate(
            "octo",
            "drybag-private",
            root=tmp_path,
            runner=absent,
            wait=waited.append,
        )
    message = str(failed.value)
    assert "gh could not be run" in message, "the real cause is in Completed.stderr"
    assert "gh auth status" not in message, "a binary that never ran cannot have a bad token"
    assert "setup --overlay <path>" in message, "the source that works today has to be named"
    # The sentence only this arm produces. `Runner`'s own docstring keeps "not installed" and
    # "hung for five minutes" apart because their remedies differ, and without this assertion
    # the mutation below survives: the next arm — `gh` ran and declined — quotes the same
    # stderr and stops after the same one call, so every other assertion here holds under it.
    assert "Install `gh` and authenticate it" in message
    assert [argv[:3] for argv in absent.calls] == [
        ["gh", "repo", "view"],
        ["gh", "repo", "create"],
    ]
    assert waited == [], "nothing was waiting to finish generating"


def test_a_gh_that_ran_and_declined_quotes_its_own_answer(tmp_path: Path) -> None:
    # The other arm of the same defect, and the one `docs/cli.md` names as the likeliest
    # reason `--template` fails: neither template repository exists yet. `gh`'s own stderr says
    # so, and is quoted rather than replaced by a guess about authentication.
    declined = Recorder(
        answers={
            THE_OWNERS_PROBE: A_TEMPLATE,
            "gh repo create": Completed(1, "", "GraphQL: Could not resolve to a Repository"),
        }
    )
    with pytest.raises(Failure) as failed:
        generate("octo", "drybag-private", root=tmp_path, runner=declined)
    message = str(failed.value)
    assert "Could not resolve to a Repository" in message
    assert "<owner>/drybag-overlay-template when the owner has published one" in message
    assert "exited 1" in message, "a binary that ran has an exit code, not a launch failure"
    assert [argv[:3] for argv in declined.calls] == [
        ["gh", "repo", "view"],
        ["gh", "repo", "create"],
    ]


def _cut_short(argv: list[str], cwd: Path) -> None:
    """Stand in for a `gh repo create --clone` whose clone was cut short: a tree with no record."""
    if argv[:3] == ["gh", "repo", "create"]:
        (cwd / argv[3].split("/")[-1] / "common").mkdir(parents=True)


@pytest.mark.parametrize(
    ("created", "on_call"),
    [
        pytest.param(Completed(TIMED_OUT, "", ""), None, id="timed-out"),
        pytest.param(Completed(1, "", "Name already exists on this account"), None, id="declined"),
        pytest.param(Completed(0, "", ""), None, id="nothing-arrived"),
        pytest.param(Completed(0, "", ""), _cut_short, id="cut-short"),
    ],
)
def test_every_refusal_after_gh_repo_create_says_the_repository_may_exist_and_how_to_record_it(
    tmp_path: Path, created: Completed, on_call: Callable[[list[str], Path], None] | None
) -> None:
    # Once `gh repo create` has run, the repository may exist on GitHub whatever `gh` answered: a
    # `gh` that hung, one that declined after creating it, a clone that never arrived or one cut
    # short. Each said "nothing was created", or "delete it and run again", whose next run then
    # failed on the name GitHub already held. Every one ends in the one remedy that works.
    runner = Recorder(
        answers={THE_OWNERS_PROBE: A_TEMPLATE, "gh repo create": created}, on_call=on_call
    )
    with pytest.raises((Failure, Refusal)) as stopped:
        generate("octo", "drybag-private", root=tmp_path, runner=runner, wait=lambda _: None)
    message = str(stopped.value)
    remedy = UNRECORDED.format(
        slug="octo/drybag-private", path=quoted(str(tmp_path / "drybag-private"))
    )
    assert message.endswith(remedy), message
    assert "nothing was created" not in message, message


def test_an_empty_destination_nothing_arrived_in_is_not_taken_for_a_clone(tmp_path: Path) -> None:
    # An empty directory at the destination is cloned into, so its being there says nothing about
    # whether a clone arrived: only something in it does. Read as "a tree arrived", it skipped the
    # retried clone and was refused as a tree that is not an overlay.
    (tmp_path / "drybag-private").mkdir()
    runner = Recorder(answers={THE_OWNERS_PROBE: A_TEMPLATE})
    with pytest.raises(Failure) as failed:
        generate("octo", "drybag-private", root=tmp_path, runner=runner)
    assert ["git", "clone"] in [argv[:2] for argv in runner.calls]
    assert "produced no tree" in str(failed.value)


# --- which template `create:` generates from ----------------------------------------------------


def test_the_owners_own_template_is_used_when_they_have_published_one(tmp_path: Path) -> None:
    # A person who publishes their own template gets their own copy, so an overlay they generate
    # is exactly the tree their published template holds. Mutation (`mutations/`'s
    # "create: never asks whose template to use"): the probe is dropped and the publisher's
    # template is always named → this reddens on the argv.
    runner = Recorder(answers={THE_OWNERS_PROBE: A_TEMPLATE}, on_call=_populate)
    created = generate("octo", "drybag-private", root=tmp_path, runner=runner)
    assert runner.calls[0] == [
        "gh",
        "repo",
        "view",
        "octo/drybag-overlay-template",
        "--json",
        "isTemplate",
    ]
    assert _template_named(runner) == "octo/drybag-overlay-template"
    assert "octo/drybag-overlay-template" in " ".join(created.notes)
    assert len([argv for argv in runner.calls if argv[:3] == ["gh", "repo", "view"]]) == 1


def test_the_publishers_template_is_used_when_the_owner_has_none(tmp_path: Path) -> None:
    # A personal account with no copy of the template could not create an overlay at all: the
    # documented contract asked for a repository nobody had told them to publish. The answer to
    # "does <owner>/drybag-overlay-template exist" is `gh`'s real not-found shape (see
    # `NO_SUCH_REPOSITORY`), and it falls back to the publisher's own public template.
    # Mutation (`mutations/`'s "create: has no template to fall back on"): the
    # fallback is dropped and the owner's template is always named → this reddens.
    #
    # Named with its host. `gh` resolves an unqualified `OWNER/REPO` on `GH_HOST`, which the runner
    # keeps, so on a GitHub Enterprise host the fallback named whoever owns `drybag` there, and
    # the owner's private overlay -- whose hooks run in every session -- was generated from it.
    # `github.com/OWNER/REPO` is looked up on github.com whatever `GH_HOST` says (measured against
    # gh 2.101.0 with `GH_HOST` set to another host). The owner's own probe above stays
    # host-relative: that repository is on the owner's own host. Mutation (`mutations/`'s "the
    # publisher's template is named on whatever host gh defaults to") → this reddens on the argv.
    runner = Recorder(answers={THE_OWNERS_PROBE: NO_SUCH_REPOSITORY}, on_call=_populate)
    created = generate("octo", "drybag-private", root=tmp_path, runner=runner)
    assert _template_named(runner) == "github.com/dry-bag/drybag-overlay-template"
    assert "github.com/dry-bag/drybag-overlay-template" in " ".join(created.notes)


def test_a_repository_that_is_not_a_template_is_not_generated_from(tmp_path: Path) -> None:
    # `gh repo create --template` on an ordinary repository fails; an owner whose repository of
    # that name is not marked as a template has not published one, and gets the publisher's.
    runner = Recorder(answers={THE_OWNERS_PROBE: NOT_A_TEMPLATE}, on_call=_populate)
    generate("octo", "drybag-private", root=tmp_path, runner=runner)
    assert _template_named(runner) == "github.com/dry-bag/drybag-overlay-template"


@pytest.mark.parametrize(
    ("answer", "said"),
    [
        pytest.param(
            Completed(
                1, "", "HTTP 401: Bad credentials (https://api.github.com/graphql)\nTry `gh auth`"
            ),
            "Bad credentials",
            id="authentication",
        ),
        pytest.param(
            Completed(
                1,
                "",
                "error connecting to api.github.com: Could not resolve host: api.github.com",
            ),
            "Could not resolve host",
            id="network-that-also-says-could-not-resolve",
        ),
        pytest.param(
            Completed(127, "", "gh could not be run: [Errno 2] gh"),
            "gh could not be run",
            id="gh-absent",
        ),
        pytest.param(
            Completed(126, "", "gh could not be run: [Errno 13] gh"),
            "…` could not be run",
            id="gh-not-started",
        ),
        pytest.param(Completed(124, "", "gh did not answer in 300s"), "300s", id="gh-hung"),
        pytest.param(Completed(0, "not json at all\n", ""), "not json at all", id="not-json"),
        pytest.param(Completed(0, '{"isTemplate": "yes"}\n', ""), "yes", id="not-a-boolean"),
    ],
)
def test_a_probe_that_failed_for_another_reason_never_switches_the_template(
    tmp_path: Path, answer: Completed, said: str
) -> None:
    # The hazard the discrimination exists for: `gh` exits 1 both for a repository that is not
    # there and for a token that is not valid, so "exit 1" cannot be read as "not found". A
    # transient failure that fell back to the publisher's template would silently generate the
    # overlay of a person who HAS their own template from somebody else's, and they would not
    # know. Only the not-found shape (`NO_SUCH_REPOSITORY`) falls back; everything else refuses
    # with gh's own words and `gh repo create` never runs.
    # Mutation: treat every non-zero exit of the probe as not-found → the first two cases redden.
    runner = Recorder(answers={THE_OWNERS_PROBE: answer}, on_call=_populate)
    with pytest.raises(Failure) as failed:
        generate("octo", "drybag-private", root=tmp_path, runner=runner)
    assert said in str(failed.value)
    assert not [argv for argv in runner.calls if argv[:3] == ["gh", "repo", "create"]]
    assert not (tmp_path / "drybag-private").exists()


def test_a_probe_failure_is_printed_without_letting_it_drive_a_terminal(tmp_path: Path) -> None:
    # `gh`'s stderr can carry whatever a proxy or a wrapper put in it, and this message reaches a
    # terminal and a CI log: a line break followed by `::error::` is a workflow command there.
    hostile = Completed(1, "", "HTTP 401\n::error::forged\x1b[2J")
    runner = Recorder(answers={THE_OWNERS_PROBE: hostile})
    with pytest.raises(Failure) as failed:
        generate("octo", "drybag-private", root=tmp_path, runner=runner)
    message = str(failed.value)
    assert "\n::error::" not in message
    assert "\x1b" not in message


HOSTILE = Completed(1, "", "HTTP 500\n::error::forged\x1b[2J")


@pytest.mark.parametrize(
    "answers",
    [
        pytest.param({THE_OWNERS_PROBE: A_TEMPLATE, "gh repo create": HOSTILE}, id="repo-create"),
        pytest.param(
            {THE_OWNERS_PROBE: A_TEMPLATE, "gh repo view octo/drybag-private": HOSTILE},
            id="clone-and-view",
        ),
    ],
)
def test_what_gh_and_git_print_cannot_drive_a_terminal(
    tmp_path: Path, answers: dict[str, Completed]
) -> None:
    # The probe's answer was clipped and quoted, and every other subprocess answer this command
    # quotes, `gh repo create`'s, `gh repo view`'s and `git clone`'s, was printed raw: a line break
    # followed by `::error::` is a workflow command in a CI log, and an escape drives a terminal.
    # They are all clipped in the one place that reads them, `printed.answered`.
    #
    # Mutation: `mutations/`'s "a subprocess's answer is quoted raw".
    runner = Recorder(answers={**answers, "git clone": HOSTILE})
    with pytest.raises(Failure) as failed:
        generate("octo", "drybag-private", root=tmp_path, runner=runner)
    message = str(failed.value)
    assert "forged" in message
    assert "\n::error::" not in message
    assert "\x1b" not in message


@pytest.mark.parametrize("ending", ["left-alone", "declined", "nothing-arrived"])
def test_every_message_naming_the_destination_prints_it_quoted(tmp_path: Path, ending: str) -> None:
    # `UNRECORDED` named the destination through `printed.quoted` and three messages beside it
    # printed it raw: the overlay left alone, a `gh repo create` that declined, and a clone that
    # left nothing. The destination is under `--home`, whose path a link can spell in bytes nobody
    # typed, and an escape in it drove the terminal and a CI log. Mutation: `mutations/`'s
    # "create: prints its destination raw".
    root = tmp_path / "x\x1b]0;owned\x07"
    root.mkdir()
    answers = {THE_OWNERS_PROBE: A_TEMPLATE}
    if ending == "left-alone":
        (root / "drybag-private").mkdir()
        (root / "drybag-private" / IDENTITY_RECORD).write_text("layout = 1\n", encoding="utf-8")
    elif ending == "declined":
        answers["gh repo create"] = Completed(1, "", "Name already exists on this account")
    try:
        said = " ".join(
            generate(
                "octo",
                "drybag-private",
                root=root,
                runner=Recorder(answers=answers),
                wait=lambda _: None,
            ).notes
        )
    except (Failure, Refusal) as stopped:
        said = str(stopped)
    assert "\x1b" not in said and "\x07" not in said, said
    assert quoted(str(root / "drybag-private")) in said, said


def test_what_git_init_prints_cannot_drive_a_terminal(tmp_path: Path) -> None:
    # The same for the local render's `git init`, whose failure is a note.
    runner = Recorder(answers={"git init": HOSTILE})
    created = render(tmp_path / "drybag-private", runner=runner)
    message = " ".join(created.notes)
    assert "forged" in message
    assert "\n::error::" not in message
    assert "\x1b" not in message


def test_a_gh_that_is_not_installed_costs_one_subprocess_at_the_probe(tmp_path: Path) -> None:
    # Absent at the very first question: one launch, the launch failure named, no
    # `gh repo create`, no clone, no wait.
    absent = Recorder(answers={"gh": Completed(127, "", "gh could not be run: [Errno 2] gh")})
    waited: list[float] = []
    with pytest.raises(Failure) as failed:
        generate(
            "octo",
            "drybag-private",
            root=tmp_path,
            runner=absent,
            wait=waited.append,
        )
    message = str(failed.value)
    assert "gh could not be run" in message
    assert "gh auth status" not in message
    assert "setup --overlay <path>" in message
    assert [argv[:3] for argv in absent.calls] == [["gh", "repo", "view"]]
    assert waited == []


# --- a local render leaves a repository ---------------------------------------------------------


def test_a_local_overlay_is_a_git_repository_on_main_with_no_remote(tmp_path: Path) -> None:
    # A local render used to leave a bare directory, so the owner's next step (commit it, push it
    # to a private repository) began with a `git init` nobody had told them about. The init is
    # `render`'s and not `render_template`'s, which the template's publisher also uses for its
    # scratch render. Mutation (`mutations/`'s "a local render leaves no git repository"): the
    # `git init` call is deleted → this reddens.
    runner = Recorder()
    created = render(tmp_path / "drybag-private", runner=runner)
    assert runner.calls == [["git", "init"], ["git", "symbolic-ref", "HEAD", "refs/heads/main"]]
    assert runner.cwds == [created.root, created.root]
    assert not any(argv[0] == "gh" for argv in runner.calls), "a render touches no GitHub"
    message = " ".join(created.notes)
    assert "git remote add origin <the private repository>" in message
    assert "git push -u origin main" in message


def test_a_local_overlay_carries_a_real_repository_on_main(tmp_path: Path) -> None:
    # The same claim against a real `git`, because a stub records the argv and cannot say whether
    # the argv makes a repository: `symbolic-ref` is `git`'s own and `HEAD` is where it shows.
    import shutil

    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    from drybag.runner import subprocess_runner

    created = render(tmp_path / "drybag-private", runner=subprocess_runner())
    head = (created.root / ".git" / "HEAD").read_text(encoding="utf-8").strip()
    assert head == "ref: refs/heads/main"
    config = (created.root / ".git" / "config").read_text(encoding="utf-8")
    assert "[remote" not in config, "no remote: the owner adds it once the repository exists"


def test_a_git_that_cannot_init_is_a_note_and_the_tree_is_kept(tmp_path: Path) -> None:
    # The tree is already rendered when `git init` runs, so a missing `git` cannot un-render it;
    # refusing would only hide a directory that exists. The note says what to run.
    runner = Recorder(answers={"git": Completed(127, "", "git could not be run: [Errno 2] git")})
    created = render(tmp_path / "drybag-private", runner=runner)
    assert (created.root / IDENTITY_RECORD).is_file()
    message = " ".join(created.notes)
    assert "git could not be run" in message
    assert "could not be run" in message and "did not run" not in message
    assert "`git init` and `git symbolic-ref HEAD refs/heads/main`" in message


def test_a_git_older_than_2_28_still_leaves_a_repository_on_main(tmp_path: Path) -> None:
    # `git init -b` arrived in git 2.28, and an older `git` refuses the option: the run said
    # `git init -b main` "did not run" and told the owner to run the same failing command.
    # `git init` and then `git symbolic-ref HEAD refs/heads/main` name the branch on every
    # version.
    #
    # Mutation: `mutations/`'s "a local render asks git init for its branch".
    runner = Recorder(answers={"git init -b": Completed(129, "", "error: unknown switch `b'")})
    created = render(tmp_path / "drybag-private", runner=runner)
    assert ["git", "init", "-b", "main"] not in runner.calls
    assert "made it a git repository on main" in " ".join(created.notes)


def test_a_git_init_that_ran_and_failed_is_said_to_have_failed(tmp_path: Path) -> None:
    # A `git` that ran and exited non-zero ran: the note says how it ended, not that it did not
    # run.
    #
    # Mutation: `mutations/`'s "a git init that failed is said not to have run".
    runner = Recorder(answers={"git init": Completed(128, "", "fatal: cannot mkdir")})
    created = render(tmp_path / "drybag-private", runner=runner)
    message = " ".join(created.notes)
    assert "`git init` exited 128" in message
    assert "did not run" not in message and "could not be run" not in message


def test_the_scratch_render_the_publisher_uses_is_not_a_repository(tmp_path: Path) -> None:
    # `render_template` is shared with `scripts/publish_template.py`, whose scratch tree is cloned
    # over and then replaced: a `.git` of its own there would be pushed as a nested repository.
    # The init belongs to `render` alone.
    from drybag.overlay.api import render_template

    rendered = render_template(tmp_path, "scratch")
    assert not (rendered / ".git").exists()


@pytest.mark.parametrize(
    "printed", [NESTED, f'{{"isTemplate": {LONG_NUMBER}}}'], ids=["nested", "long"]
)
def test_a_template_probe_past_the_parser_is_no_answer(printed: str) -> None:
    # Valid JSON that `json.loads` answers with `RecursionError` or a plain `ValueError`: the
    # probe caught only `JSONDecodeError`, so either ended `create:` in an internal error
    # where an answer that is not JSON reads as no answer. Mutation (declared): the catch narrowed
    # to `JSONDecodeError` again.
    assert _is_template(printed) is None


def test_a_template_probe_past_the_depth_bound_is_no_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The probe's answer goes through the one JSON object reader and its depth bound. Mutation
    # (declared): `mutations/`'s "the template probe parses with a bare json.loads".
    monkeypatch.setattr(jsonobject, "DEPTH_CAP", 4)
    assert _is_template('{"isTemplate": true, "a": [[[[]]]]}') is None


@pytest.mark.parametrize(
    "argv",
    [
        ["overlay", "create", "--owner", "octo", "--local"],
        ["overlay", "init", "--owner", "octo"],
        ["overlay", "publish-template", "--owner", "octo"],
    ],
    ids=["create", "init", "publish-template"],
)
def test_the_overlay_group_no_longer_creates_initialises_or_publishes(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    # One entry for an overlay: `setup --overlay <path>` renders one and `setup --overlay
    # create:<owner>/<name>` generates one, and publishing the template is the maintainer's
    # script. A second spelling of either is a second thing to keep true.
    from drybag.cli import build_parser, discover_registrars

    with pytest.raises(SystemExit) as exited:
        build_parser(discover_registrars()).parse_args(argv)
    assert exited.value.code == 2
    assert f"invalid choice: '{argv[1]}'" in capsys.readouterr().err

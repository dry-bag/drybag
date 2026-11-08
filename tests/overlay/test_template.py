from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest

from drybag import __version__
from drybag.hooks.api import EVENTS
from drybag.overlay.identity import NO_RECORD, NOT_A_RECORD, overlay_fault
from drybag.overlay.layout import IDENTITY_RECORD, OVERLAY_FILES
from drybag.overlay.template import template_root, templates
from drybag.presets import load_preset
from drybag.printed import quoted
from drybag.scaffold import MANIFEST_PATH


def _json_files() -> list[Path]:
    return sorted(template_root().rglob("*.json"))


def test_the_template_tree_is_reachable_at_all() -> None:
    # The non-vacuity guard, and it is not hypothetical: `rglob` over a directory that is not
    # in the wheel or the sdist returns nothing, and every assertion below then passes by
    # finding no files to fail on. The standard-library walk in
    # `tests/boundaries/test_layering.py` carries the same idiom for the same reason.
    assert template_root().is_dir()
    assert _json_files(), "no JSON in templates/overlay — the invariants below are vacuous"


def test_the_template_ships_no_allow_rule_anywhere() -> None:
    # An overlay template that ships an `allow` rule or a hook fails the release, and this test
    # over templates/overlay/ is what fails it. The plugin author may never grant a permission;
    # only the machine owner may, by editing their own instance after it is theirs.
    for path in _json_files():
        assert "allow" not in _keys(json.loads(path.read_text(encoding="utf-8"))), path


def test_the_template_ships_no_hook_entry() -> None:
    # Same rule. An overlay hook is the machine owner's to add; one shipped in the template
    # would execute on every machine that created an instance from it.
    #
    # The `if "hooks" in payload` guard this replaced was the defect: a file with no `hooks`
    # key was not examined at all, so a hook written under a bare top-level event key —
    # `{"PreToolUse": [...]}`, the shape `.codex/hooks.json` uses — passed. Both spellings are
    # refused now, and the event vocabulary comes from `hooks.api.EVENTS` rather than a second
    # copy of it here, so a sixth event is covered the day it is declared.
    #
    # Mutation: put `{"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command",
    # "command": "curl evil.example"}]}]}` into common/claude/hooks.json -> reddens.
    for path in _json_files():
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload.get("hooks", {}) == {}, path
        assert not set(EVENTS) & _keys(payload), path


def test_the_preset_grants_nothing_anywhere_in_it() -> None:
    # The same rule for the other shipped file that can carry permissions. An earlier draft
    # asserted `"allow" not in preset["deny"]` — an allow key nested INSIDE the deny table,
    # which nobody writes. An allow rule is forbidden anywhere in anything the author ships.
    assert "allow" not in _keys(load_preset("recommended"))


def test_the_template_ignores_env_files() -> None:
    # The overlay may hold hostnames, user ids and env-file paths; it never holds
    # credentials. This is the cheap half of that promise; gitleaks is the other half.
    #
    # The patterns, from the non-comment lines, and not `".env" in text`: that substring test
    # was satisfied by the word appearing in the file's own explanatory comment, so commenting
    # every pattern out left it green with nothing ignored at all.
    #
    # Mutation: comment out the `.env` line in templates/overlay/.gitignore -> reddens.
    text = (template_root() / ".gitignore").read_text(encoding="utf-8")
    patterns = {
        stripped for line in text.splitlines() if (stripped := line.strip()) and stripped[0] != "#"
    }
    assert patterns, "an all-comment .gitignore ignores nothing"
    assert {".env", ".env.*"} <= patterns, patterns


# A `rev:` a pre-commit hook may carry: a full commit sha, the only reference its owner cannot
# move. A release tag is a name its owner can move (the gitleaks release reads `immutable: false`)
# and a branch is the whole of what this row exists to refuse, so neither passes.
_PINNED_REV = re.compile(r"\A[0-9a-f]{40}\Z")


def test_the_template_pins_gitleaks_at_a_revision() -> None:
    # GitHub does not scan private repositories on a personal plan, so gitleaks is the scan.
    # An unpinned rev is a third party choosing what runs on the owner's machine.
    #
    # The *value* of `rev:`, and not `"rev:" in config`: that membership test is true of every
    # possible pre-commit configuration, including one pinned at `main`, which is exactly the
    # state it is named for refusing.
    #
    # Mutations: `mutations/`'s "the overlay template follows gitleaks' default branch" and
    # "the overlay template's hook goes back to naming gitleaks by its tag".
    config = (template_root() / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert "gitleaks" in config
    # A trailing `# frozen: vX.Y.Z` comment is the release a sha is, and is not part of the value.
    revisions = re.findall(r"^\s*rev:\s*(\S+)(?:\s+#.*)?\s*$", config, re.MULTILINE)
    assert revisions, "no `rev:` at all, so the hook follows whatever the repo's default branch is"
    for revision in revisions:
        assert _PINNED_REV.match(revision), revision


def test_the_template_ships_permissions_that_are_neither_granted_nor_pretended() -> None:
    # This file used to ship `deny: ["Read(.env*)", "Read(**/.env*)"]`, asserted here by value
    # and called "the template's only actual protection". It was not protection at all:
    # `attach.permissions._allow_rules` reads `permissions.allow` and nothing else, so no deny
    # rule in this file has ever reached a bound repository, a harness, or any other reader in
    # the tree. Meanwhile `presets/recommended.toml`'s `[deny] global` — which `setup` merges
    # into `<home>/.claude/settings.json`, where it does fire for every project on the machine —
    # had grown a third rule this copy never got. A dead duplicate, one rule behind the live
    # one, documented as live.
    #
    # So the rules went, and the assertion moved to where they fire:
    # `tests/setup/test_machine.py::test_the_preset_denies_reading_env_files_by_value` and
    # `tests/setup/test_setup.py::test_setup_writes_the_machine_file_and_the_deny_rules`.
    # What is left here is the shape: a `permissions` table with no rule of any kind in it.
    #
    # Mutation: `mutations/`'s "the overlay template starts granting a permission".
    payload = json.loads(
        (template_root() / "common" / "claude" / "permissions.json").read_text(encoding="utf-8")
    )
    # `.get` and an explicit `{} ==`, not `[...]`: a mutation that emptied the whole file would
    # otherwise raise `KeyError`, and a crash is a worse proof than an assertion.
    assert payload.get("permissions") == {}, payload


# A write permission, in every spelling a workflow can grant one. `write-all` is the one that
# matters most and the one the first draft of this test missed: `permissions: write-all` on a
# *job* grants every scope while a top-level `permissions: contents: read` sits above it looking
# correct, which is the same escalation shape with the top-level assertion intact.
_WRITE_SCOPE = re.compile(r"^\s*[a-z-]+:\s*write(-all)?\s*$", re.MULTILINE)
# A pinned action: `owner/repo@<40 hex>`, with the release it is in a trailing comment. Pins are
# immutable (principle 9 of `docs/methodology/principles.md`), and a full-length commit sha is the
# only immutable reference GitHub Actions has. The comment's shape is this repository's own
# convention, taken from `.github/workflows/`, where every `uses:` is already pinned this way -- the
# overlay template was the one place it was not. `v7`, `v6.0.0` and everything between are all
# spellings that convention uses, so all three are accepted: a test that rejected the house style
# would be a trap for whoever next bumps a pin.
_PINNED_USES = re.compile(r"\A[\w.-]+/[\w.-]+@[0-9a-f]{40} # v\d+(\.\d+){0,2}\Z")


def _scan_workflow() -> str:
    return (template_root() / ".github" / "workflows" / "scan.yml").read_text(encoding="utf-8")


def _block(text: str, key: str) -> list[str]:
    """The two-space-indented keys directly under the top-level `key:`, and nothing else.

    A regex over the whole file was the first draft and it was wrong in the way that matters:
    `^  ([a-z_]+):` matches every two-space-indented key anywhere, so `triggers` also held
    `contents` and `gitleaks` -- and the non-vacuity guard below would then have passed with the
    whole `on:` block deleted. Stdlib-only, so this is a reader and not `yaml.safe_load`.
    """
    lines = text.splitlines()
    if f"{key}:" not in lines:
        return []
    found: list[str] = []
    for line in lines[lines.index(f"{key}:") + 1 :]:
        if line and not line.startswith(" "):
            break
        if (match := re.match(r"^  ([A-Za-z_][\w-]*):", line)) is not None:
            found.append(match.group(1))
    return found


def _top_level_lines(text: str, key: str) -> list[str]:
    """The non-comment lines of the top-level `key:` block, nested keys included."""
    lines = text.splitlines()
    if f"{key}:" not in lines:
        return []
    found: list[str] = []
    for line in lines[lines.index(f"{key}:") + 1 :]:
        if line and not line.startswith(" "):
            break
        if line.strip() and not line.strip().startswith("#"):
            found.append(line)
    return found


def test_the_scan_workflow_never_runs_a_forks_head_with_the_repositorys_own_token() -> None:
    # Nothing asserted anything about this file before -- the reviewer rewrote it to
    # `pull_request_target:` with `contents: write` and `id-token: write` and all 43 cases
    # passed. Both halves are asserted: the trigger that makes a fork's code privileged, and
    # any write scope, because a secret scan needs read scopes only (`contents`, and `pull-requests`
    # for the action's reads of a pull request, asserted below) and never a write one. That the
    # workflow-level block is exactly those two scopes, and that no job replaces it, is asserted
    # below.
    #
    # Mutations: `mutations/`'s "the overlay's secret scan runs a fork's head" and "the
    # overlay's secret scan is given a write token".
    text = _scan_workflow()
    triggers = _block(text, "on")
    assert triggers, "no `on:` block was found, so the assertion below measures nothing"
    assert "pull_request_target" not in triggers, triggers
    assert _WRITE_SCOPE.search(text) is None, _WRITE_SCOPE.search(text)


def test_the_scan_workflow_can_read_a_pull_requests_commits_in_a_private_repository() -> None:
    # On `pull_request` the gitleaks action calls `GET /repos/{owner}/{repo}/pulls/{n}/commits`
    # to find what to scan, and on a private repository -- which an overlay is, `create:`
    # passes `--private` -- that endpoint needs the "Pull requests: read" permission. A
    # `permissions:` block naming `contents` alone leaves every other scope at none, so the scan
    # would fail for want of it. The block is asserted by value and in full: exactly these two
    # read scopes, so that neither a dropped scope nor an added one passes. And no job carries a
    # `permissions:` key of its own, because a job's block replaces the workflow's: a job with
    # `permissions: read-all`, or with `contents: read` alone, would leave this block looking
    # right above a token that is not the one it describes.
    #
    # Mutations: `mutations/`'s "the overlay's secret scan cannot list a pull request's
    # commits" and "the overlay's secret scan sets its own permissions on the job".
    text = _scan_workflow()
    assert re.search(
        r"^permissions:\n  contents: read\n  pull-requests: read\n(?!  )", text, re.MULTILINE
    ), text
    jobs = _top_level_lines(text, "jobs")
    assert jobs, "no `jobs:` block was found, so the assertion below measures nothing"
    assert not [line for line in jobs if "permissions" in line], jobs


def test_the_scan_workflow_checkout_leaves_no_token_behind() -> None:
    # The job never pushes, so the checkout has no use for the token it would otherwise persist
    # for every later step, the third-party action among them. `fetch-depth: 0` sits in the same
    # `with:` block, so the key is looked for by value and not by name.
    #
    # Mutation: `mutations/`'s "the overlay's secret scan checks out with a persisted token".
    assert re.search(r"^ +persist-credentials: false$", _scan_workflow(), re.MULTILINE)


def test_the_scan_workflow_skips_a_repository_marked_as_a_template_and_scans_the_rest() -> None:
    # The public template repository is organisation-owned, and the action fails every run there
    # for want of a licence key. A repository made from the template has `is_template` false, so
    # the condition below runs it; any repository marked as a template, an owner's own published
    # one or an overlay flagged later, is skipped with it. The expression is asserted whole: its
    # inverse, `is_template` without the `!`, would scan the template and skip every overlay,
    # which is the worst of both.
    #
    # Mutations: `mutations/`'s "the overlay's secret scan runs on the template repository"
    # and "the overlay's secret scan skips every repository made from the template".
    lines = _top_level_lines(_scan_workflow(), "jobs")
    assert "    if: ${{ !github.event.repository.is_template }}" in lines, lines


def test_the_scan_workflow_runs_the_gitleaks_the_pre_commit_hook_pins() -> None:
    # gitleaks-action v3.0.0 runs its own default, 8.24.3, unless `GITLEAKS_VERSION` says
    # otherwise, so pinning the action at a sha does not choose the rules a push is scanned by.
    # The workflow is the scan that cannot be skipped and the hook is the one that can; the two
    # name one release, and the hook's `rev:` is a sha whose release is its `# frozen:` comment.
    #
    # Mutations: `mutations/`'s "the overlay's secret scan runs the action's older default
    # gitleaks", "the overlay's secret scan runs a different gitleaks than the hook" and "the
    # overlay template's hook goes back to naming gitleaks by its tag".
    config = (template_root() / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    frozen = re.findall(
        r"^\s*rev:\s*[0-9a-f]{40}\s+# frozen: v(\d+\.\d+\.\d+)$", config, re.MULTILINE
    )
    assert len(frozen) == 1, "the hook's `rev:` is not a sha followed by `# frozen: vX.Y.Z`"
    pinned = re.findall(r'^ +GITLEAKS_VERSION: "(\d+\.\d+\.\d+)"$', _scan_workflow(), re.MULTILINE)
    assert pinned == frozen, (pinned, frozen)


def test_the_scan_workflow_pins_every_action_at_an_immutable_revision() -> None:
    # The same argument the `rev:` case above makes one directory over: a tag is
    # a name its owner can move. `actions/checkout@v7` and `gitleaks/gitleaks-action@v3` would be
    # mutable major tags in a file that runs with `secrets.GITHUB_TOKEN` over a repository
    # holding the owner's rules and notes -- while the sibling `.pre-commit-config.yaml` argued
    # at length that an unpinned revision "lets somebody else choose what runs on your machine".
    # A full-length commit sha is the only immutable reference Actions has.
    #
    # Mutations: `mutations/`'s "the overlay's secret scan follows a moveable action tag" and
    # "the overlay's secret scan follows a moveable gitleaks-action tag".
    steps = [
        stripped.removeprefix("- uses:").strip()
        for line in _scan_workflow().splitlines()
        if (stripped := line.strip()).startswith("- uses:")
    ]
    assert len(steps) == 2, steps
    for step in steps:
        assert _PINNED_USES.match(step), step


@pytest.mark.parametrize("relative", sorted(OVERLAY_FILES))
def test_every_declared_file_exists(relative: str) -> None:
    # The list and the tree are two statements of one thing, and they drift. Asserting from the
    # list catches a deleted file; the next test catches an undeclared one.
    assert (template_root() / relative).is_file()


def test_no_file_in_the_tree_is_undeclared() -> None:
    root = template_root()
    present = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}
    assert present == set(OVERLAY_FILES)


def test_the_identity_record_is_the_last_file_a_render_writes_and_a_clone_checks_out() -> None:
    # A tree is an overlay exactly when its record parses, so the record comes last both ways a
    # tree is made, and one cut short is never an overlay: a render writes in this order, and git
    # checks a tree out in path order, in which the record's path has to sort after every other.
    assert OVERLAY_FILES[-1] == IDENTITY_RECORD == max(OVERLAY_FILES)


def test_the_templates_plan_cleanly_into_an_empty_directory(tmp_path: Path) -> None:
    from drybag.scaffold import apply, plan

    # The overlay writes through the scaffold engine like every other area, which is what makes
    # `overlay upgrade` the engine's hash-and-skip rule rather than a second implementation of it.
    planned = plan(tmp_path, templates())
    assert planned.refusals == ()
    assert len(planned.actions) == len(OVERLAY_FILES)
    apply(tmp_path, planned)
    assert (tmp_path / ".drybag" / "manifest.json").is_file()


def test_the_manifest_records_a_comparable_version(tmp_path: Path) -> None:
    from drybag.scaffold import apply, plan
    from drybag.scaffold.manifest import Manifest

    # `[defaults.drybag]` carries no `version`, and the engine stamps one into every Record.
    # A record written with "" is a record `upgrade` and `doctor` can never compare against.
    apply(tmp_path, plan(tmp_path, templates()))
    records = Manifest.read(tmp_path).records
    assert records and {record.version for record in records.values()} == {__version__}


def _keys(value: object) -> set[str]:
    """Every key anywhere in a parsed JSON/TOML document.

    Recursive on purpose: the risk is an allow rule *anywhere* in a shipped file, and
    a top-level membership test misses `permissions.allow`, which is where one would actually
    be written.
    """
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in _keys(item)}
    if isinstance(value, list):
        return {key for item in value for key in _keys(item)}
    return set()


# --- the README that counts the files, checked against the files ------------------------------

# The words this document could plausibly spell a file count with. Local rather than imported
# from `tests/test_documents.py` because that map stops at twelve and this one has to reach
# past it — not because a cross-module import is forbidden; the test tree is an importable
# package and nine of its modules import across it.
_COUNT_WORDS = {
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
}
_STATED_COUNT = re.compile(r"renders (\w+) files here")


def _rendered_paths() -> tuple[str, ...]:
    """Every file a render leaves in a fresh instance, as the README has to describe it.

    `OVERLAY_FILES` plus the scaffold manifest, which is the one path the template tree does not
    hold: `scaffold.apply` writes `.drybag/manifest.json` as the record `overlay upgrade` keys
    on, so it is in the instance without ever having been in `templates/overlay/`. That is
    exactly how it went missing from a README that counts them.
    """
    return (*OVERLAY_FILES, str(MANIFEST_PATH))


def test_the_overlay_readme_counts_the_files_a_create_actually_leaves() -> None:
    # The template README said "renders fifteen files here" and a rendered overlay has sixteen —
    # `.drybag/manifest.json`, the file the project README advertises as the overlay's "own
    # upgrade manifest", in neither of that README's two tables. The count was written by hand
    # against `OVERLAY_FILES` and nothing read the document, which is how a file the scaffold
    # engine adds slips past a sentence that counts them.
    #
    # Mutation: `mutations/`'s "the overlay README stops counting the manifest".
    expected = _rendered_paths()
    assert expected, "no overlay files at all — every assertion below is vacuous"
    text = (template_root() / "README.md").read_text(encoding="utf-8")
    stated = _STATED_COUNT.search(text)
    assert stated is not None, "the overlay README no longer says how many files a create leaves"
    assert _COUNT_WORDS[stated.group(1).lower()] == len(expected), stated.group(1)


def test_the_capability_files_are_spelled_once_and_are_shipped_files() -> None:
    # The comment beside `CAPABILITY_FILES` said the two names were "not spelled twice"
    # while the tuple was built by filtering `OVERLAY_FILES` against a second spelling of
    # them. One spelling now: `CAPABILITY_NAMES` is unpacked into `OVERLAY_FILES` and
    # `CAPABILITY_FILES` is that same tuple.
    from drybag.overlay.layout import CAPABILITY_FILES, CAPABILITY_NAMES, OVERLAY_FILES

    # Against the SHIPPED tree, not against `OVERLAY_FILES`: with one spelling the subset
    # holds by construction, so the assertion that can fail is that each name is a file the
    # template actually carries. Mutation: rename one entry of `CAPABILITY_NAMES` to
    # `common/claude/allow.json` -> it is no longer under `template_root()` and this reddens.
    # The count by value, first and on its own. The derived form this replaced could not be
    # emptied without emptying `OVERLAY_FILES` too; one spelling removed that guard, and
    # `CAPABILITY_NAMES = ()` satisfies the alias comparison, the subset (`OVERLAY_FILES`
    # unpacks the tuple) and the loop below, while silently emptying `overlay upgrade`'s
    # decision list — the one list it diffs and asks about regardless of hash.
    assert len(CAPABILITY_NAMES) == 2, CAPABILITY_NAMES
    assert CAPABILITY_FILES == CAPABILITY_NAMES
    assert set(CAPABILITY_NAMES) <= set(OVERLAY_FILES)
    for relative in CAPABILITY_NAMES:
        assert (template_root() / relative).is_file(), relative


def _is_placeholder(relative: str) -> bool:
    """Whether this path is a directory's own documentation rather than a file in its own right.

    A render drops a README into each directory the owner fills — `common/memory/`'s
    `_README.md` and `projects/`'s `README.md`. The template README describes those as
    *directories* on purpose, and naming the placeholders inside them would be noise. Derived
    from the basename rather than listed, so a third such directory needs no edit here. The root
    `README.md` is no placeholder; the `/` conjunct below is what excludes it. `common/memory/`'s
    is `_README.md` because the note reader skips a name that starts with `_`.
    """
    return "/" in relative and relative.rsplit("/", 1)[1] in ("README.md", "_README.md")


def test_the_overlay_readme_accounts_for_every_file_a_create_leaves() -> None:
    # The count is only half of it: fifteen rows and a sixteenth file is caught above, but so is
    # sixteen rows describing the wrong sixteen files, and only this half says which.
    #
    # **A file is accounted for by its full path**, and an ancestor directory is accepted only
    # for a placeholder. The first draft of this accepted any ancestor, and a mutation that
    # renamed a file in the README survived it, the file's directory standing in for it.
    text = (template_root() / "README.md").read_text(encoding="utf-8")
    assert text.strip(), "an empty README accounts for nothing"
    missing = []
    for relative in _rendered_paths():
        if _is_placeholder(relative):
            directory = f"{relative.rsplit('/', 1)[0].split('/')[0]}/"
            names = [relative, f"{relative.rsplit('/', 1)[0]}/", directory]
        else:
            names = [relative]
        if not any(name in text for name in names):
            missing.append(relative)
    assert missing == [], missing


def test_the_template_ships_a_dependabot_configuration_for_its_pinned_actions() -> None:
    # The scan workflow pins both actions by full-length SHA, and nothing told the owner
    # a pin was two years old. The same Dependabot shape this repository uses for its own
    # actions. Mutation: delete the `github-actions` ecosystem line -> reddens.
    text = (template_root() / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    assert "package-ecosystem: github-actions" in text
    assert ".github/dependabot.yml" in OVERLAY_FILES


# --- the rendered overlay is valid, reachable and honest ---------------------------------------


def _render_into(tmp_path: Path) -> Path:
    from drybag.overlay.api import render_template

    return render_template(tmp_path, "rendered")


def test_nothing_in_a_fresh_common_memory_fails_the_note_reader(tmp_path: Path) -> None:
    # The template's own documentation for `common/memory/` was a `README.md` with no
    # frontmatter, which `memory index --check` reads as a note, cannot parse, and reports —
    # exit 1 in every project attached to a freshly created overlay. The store walk skips a name
    # that starts with `_` (`memory.notes.walk`), so the documentation is `_README.md`.
    # Asserted through the real reader rather than by a name: whatever else lands in this
    # directory has to be a note or be skipped.
    # Mutation: rename `_README.md` back to `README.md` (and `OVERLAY_FILES` with it) → reddens
    # on `unreadable`.
    from drybag.memory.notes import walk

    rendered = _render_into(tmp_path)
    directory = rendered / "common" / "memory"
    assert (directory / "_README.md").is_file(), "the documentation moved, it did not go"
    assert list(directory.glob("*.md")), "an empty directory makes the walk below vacuous"
    walked = walk(rendered / "common", ["memory"])
    assert walked.unreadable == []


# --- what names a tree an overlay -------------------------------------------------------------


def test_a_rendered_overlay_carries_its_identity_record_and_no_plugin_manifest(
    tmp_path: Path,
) -> None:
    # The overlay is no plugin any more: the delivery drybag renders on the machine carries
    # its hooks, skills and rules, so the manifests that made the tree installable, and the hooks
    # file it fired as a plugin, went. What names it an overlay is its identity record.
    rendered = _render_into(tmp_path)
    record = tomllib.loads((rendered / IDENTITY_RECORD).read_text(encoding="utf-8"))
    assert set(record) == {"requires", "layout"}, record
    assert record["layout"] == 1
    for gone in (".claude-plugin", ".codex-plugin", "hooks"):
        assert not (rendered / gone).exists(), gone
    assert overlay_fault(rendered) is None


def test_a_tree_without_the_identity_record_is_no_overlay_and_is_told_what_to_add(
    tmp_path: Path,
) -> None:
    # An overlay made before the record shipped carries plugin manifests and no record, and no
    # code migrates it: the refusal names the file and the keys it holds, so the owner adds it in
    # one step. Mutation: `mutations/`'s "the overlay probe stops asking for the identity record".
    rendered = _render_into(tmp_path)
    (rendered / IDENTITY_RECORD).unlink()
    assert overlay_fault(rendered) == NO_RECORD.format(root=quoted(str(rendered)))
    for named in (IDENTITY_RECORD, "requires = ", "layout = 1"):
        assert named in NO_RECORD, named


@pytest.mark.parametrize(
    "body",
    ["owner = 'o'\nlayout = 2\n", 'layout = "1"\n', "layout = true\n", "owner = \n", "\n"],
    ids=["another-layout", "a-string", "a-boolean", "not-toml", "no-layout"],
)
def test_a_record_that_is_not_a_layout_1_record_is_no_overlay(tmp_path: Path, body: str) -> None:
    # The one layout this drybag reads is 1; a record naming another, or one that does not
    # parse, names nothing it can act on. `true` is no 1, though Python compares them equal.
    # Mutations: `mutations/`'s "the overlay probe takes any record for an overlay" ->
    # `another-layout`; "the overlay probe takes true for layout 1" -> `a-boolean`.
    rendered = _render_into(tmp_path)
    (rendered / IDENTITY_RECORD).write_text(body, encoding="utf-8")
    assert overlay_fault(rendered) == NOT_A_RECORD.format(root=quoted(str(rendered)))

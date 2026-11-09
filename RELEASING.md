# Releasing drybag

Version discipline itself is enforced — `scripts/release.py check` cross-checks seven sources and
a tag, and runs in CI. What was undocumented is everything around it: how to cut a release at all.
This file is that, so the bus factor of the release process is not one.

The sequence, once, before the detail: `scripts/release.py check` → towncrier assembles
`CHANGELOG.md` from the `changelog.d/` fragments → the release commit, into whose marketplace
entry `scripts/release.py pin` writes the plugin commit it releases → `claude plugin tag` and the
`vX.Y.Z` tag, pushed without `main` → the release workflow's `build` job checks the tag, the pin
included, tests and builds, and the same workflow's `attest` job computes the plugin commit again
and attests the packages and the plugin tree's manifest → `scripts/publish_plugin.py` pushes that
pinned commit to `dry-bag/drybag-plugin`, the repository the plugin is installed from, from
your own authenticated checkout → the `pypi` approval, whose two jobs first check that the plugin
repository's tag names the pinned commit and then release the PyPI upload and the GitHub Release,
attached to `vX.Y.Z` only and never to the floating `v1`, which immutable releases would freeze →
`main` moves to the release commit → `scripts/publish_template.py`, which renders
`templates/overlay/` and pushes it to `dry-bag/drybag-overlay-template`, the template repository,
from your own authenticated checkout → from `1.0.0` on, the `v1` alias moves →
the release returns to `dev` (section 5). Both pushes to a second repository are yours, so the
public repository's CI holds no credential that can write one.

## 1. The sources

`uv run python scripts/release.py check` refuses unless these agree:

| Source | Where the version lives |
|---|---|
| `pyproject.toml` | `project.version` |
| `uv.lock` | the `drybag` package entry — stale unless `uv sync` has run |
| `src/drybag/__init__.py` | `__version__` |
| `.claude-plugin/plugin.json` | `version` |
| `.codex-plugin/plugin.json` | `version` |
| `CHANGELOG.md` | the first `## <version>` heading after the towncrier marker |
| `.claude-plugin/marketplace.json` | the plugin entry's `ref`, `vX.Y.Z`: the tag of `dry-bag/drybag-plugin` the marketplace fetches the plugin at; its `sha` beside it is the commit that tag names, and no version |

The marketplace entry is held to one shape besides its `ref`: exactly one entry named
`drybag`, a `url` source naming `https://github.com/dry-bag/drybag-plugin.git`, pinned by
`ref` and by `sha`, and no `version` of its own. The `ref` names the plugin repository's tag; the
`sha` names the commit that tag holds, so a tag moved there does not change what installs. That
commit is the plugin commit, and the release commit can name it before the plugin repository
holds it, because it is computed from the release commit alone: the plugin tree, a fixed author,
committer and date, a message naming the version, and as its parent the `sha` the release
commit's first parent pins — the plugin commit pushed last, the previous release's or a stopped
release's (section 5), which is what the plugin repository's `main` must hold — or none for
a plugin repository with no history, which this one is not (section 3 seeds it). `scripts/release.py pin` writes it
(section 2, step 5). Plain `check` holds only the `sha`'s shape, 40 lowercase hex characters,
because between releases the entry pins the plugin commit pushed last, which no later tree makes.

`scripts/release.py check --tag vX.Y.Z` adds the tag as a further source, tightens one rule and
adds two: a fragment still pending in `changelog.d/` is a finding rather than a licence for
`CHANGELOG.md` to lag, a plugin tree holding more than 512 files is refused (section 2 says where
that tree comes from), and so is a marketplace entry whose `sha` is not the plugin commit, which it
computes again from `HEAD`, the commit the tag names where step 6 and `release.yml` run it. That is
the form `release.yml` runs. Section 6 is the scripts' own reference.

## 2. Cutting a release

**If this is the first release, do section 3 first.** The `pypi` environment is the only human
gate this process has, and it is a gate only once it exists: GitHub **auto-creates** an
environment that a job names and the repository does not have, with no protection rules on it.
So a first release run top to bottom without section 3 waits for nobody — `publish` runs
unapproved and fails on Trusted Publishing for want of a pending publisher, and
`github-release` runs unapproved and creates a public GitHub Release. Section 3 is what makes
step 7's sentence true.

**If this is the first release published from the plugin repository, do section 3's "The plugin
repository" first.** That is the first release after the rename too, not only the first release ever: until
`dry-bag/drybag-plugin` exists with its four rulesets, step 1's read-back of them answers
`404` and step 7's push has nowhere to go. The first release after the rename also finds this
repository's own two tag rulesets as the transfer left them, guarding the former product's `--v*` tags:
replace that pattern with `refs/tags/drybag--v*` in both before step 1, whose read-back holds exactly
the two patterns.

**The plugin is published from a repository of its own.** The marketplace entry here fetches it
from `dry-bag/drybag-plugin`, a `url` source pinned to the release's tag by `ref` and to the
plugin commit by `sha` (section 1), and that repository's root is the tree `scripts/plugin_tree.py`
generates from a commit of this one: the eight paths the plugin's runtime reads — the two plugin
manifests, `hooks/`, `scripts/drybag`, `src/drybag/`, `skills/`, `README.md` and
`LICENSE` — and the listing icon, `.claude-plugin/icon.png`, which the directory takes once, at
the first submission, and nothing else. Its only tags are the `vX.Y.Z` step 7 pushes there; it
carries no `drybag--vX.Y.Z`, which nothing there reads. Its `main` is the plugin commit
pushed last, a
spent release's when that release stopped after its push, and moves only by fast-forward, each
release's commit the child of the one before, so a release commit cut on the wrong base is
refused (section 5). The Claude plugin directory holds a plugin of more than 512 files for a
reviewer ("Keep the plugin to 512 files or fewer", in its
[pre-submission checklist](https://claude.com/docs/plugins/pre-submission-checklist)), and the
count is the generated tree's: `tests/test_payload.py` holds it on every pull request, and
`scripts/release.py check --tag` again on the commit a release is cut from, before `release.yml`
builds. Not a subfolder of this repository: the same page holds every version of a plugin in a
subfolder whose hook runs a non-shell file or a shell script that calls other files, and
`hooks/run-hook.sh` runs the Python launcher. A file the runtime needs outside those nine paths
is added to `PLUGIN_PATHS` in `scripts/plugin_tree.py`, or the plugin repository never holds it.

1. **Be on `main`, current, and green.** The release workflow builds from the tag, so anything
   not merged is not in the release. `main` is current once `dev` is merged into it, and a release
   is always cut on `origin/main`, after a stopped release too (section 5, "Which commit a release
   is cut on"): the `git log` lists what your `main` holds that `origin/main` does not, which is
   nothing, or after a stopped release that release's commit alone, decorated with the spent tags
   that keep it. Anything else it lists is work `git switch -C` would leave behind: stop, and put
   it on a branch of its own first. `git switch -C` then makes your `main` `origin/main`, and
   the merge brings `dev` into it, locally: `main` is not pushed until step 7.

   ```bash
   git fetch origin
   git log --oneline --decorate origin/main..main   # nothing, or a spent release commit
   git switch -C main origin/main
   git merge --no-ff --no-edit origin/dev
   uv run pytest -n auto --cov --cov-report=term-missing --cov-fail-under=92
   uv run ruff check . && uv run ruff format --check . && uv run mypy
   uv run python scripts/mutation_oracle.py
   uv run python scripts/release.py check
   plugin="$(mktemp -d)"
   uv run python scripts/plugin_tree.py render --root . --rev HEAD \
     --out "$plugin/tree" --manifest-file "$plugin/plugin-tree.txt"
   claude plugin validate --strict "$plugin/tree/.claude-plugin/plugin.json"
   claude plugin validate "$plugin/tree/.codex-plugin/plugin.json"
   claude plugin validate --strict .claude-plugin/marketplace.json
   claude plugin tag --dry-run .
   ```

   The two plugin manifests are validated where the render writes them, as `ci.yml` validates
   them: the plugin repository's root is that tree, rendered from the commit, not this checkout.
   The marketplace stays here and is validated where it is.

   **And read back the four settings a tag relies on, and where the plugin repository's `main`
   is**, because none of them lives in the tree and a repository transfer carries each one over
   as it was rather than as section 3 says it should be:

   ```bash
   gh api repos/dry-bag/drybag/rulesets --jq '[.[] | select(.name == "release tags" or
       .name == "release tag creation")] | sort_by(.name) | .[].id' |
     xargs -I{} gh api repos/dry-bag/drybag/rulesets/{} \
     --jq '[.name, .target, .enforcement, (.conditions.ref_name.include | sort),
            ([.rules[].type] | sort),
            [(.bypass_actors // [])[] | "\(.actor_type) \(.actor_id) \(.bypass_mode)"]]'
   # ["release tag creation","tag","active",["refs/tags/drybag--v*","refs/tags/v*.*.*"],["creation"],["RepositoryRole 5 always"]]
   # ["release tags","tag","active",["refs/tags/drybag--v*","refs/tags/v*.*.*"],["deletion","update"],[]]
   gh api repos/dry-bag/drybag-plugin/rulesets --jq 'sort_by(.name) | .[].id' |
     xargs -I{} gh api repos/dry-bag/drybag-plugin/rulesets/{} \
     --jq '[.name, .target, .enforcement, (.conditions.ref_name.include | sort),
            ([.rules[].type] | sort),
            [(.bypass_actors // [])[] | "\(.actor_type) \(.actor_id) \(.bypass_mode)"]]'
   # ["main","branch","active",["refs/heads/main"],["deletion","non_fast_forward"],[]]
   # ["no tag-shaped branches","branch","active",["refs/heads/v*"],["creation"],[]]
   # ["release tag creation","tag","active",["refs/tags/v*.*.*"],["creation"],["RepositoryRole 5 always"]]
   # ["release tags","tag","active",["refs/tags/v*.*.*"],["deletion","update"],[]]
   git ls-remote https://github.com/dry-bag/drybag-plugin.git refs/heads/main
   gh api repos/dry-bag/drybag-plugin/git/ref/heads/main --jq .object.sha
   grep '"sha"' .claude-plugin/marketplace.json
   # one commit on all three lines, the plugin repository's main; for an empty plugin repository
   # the first prints nothing, and gh api answers "gh: Git Repository is empty. (HTTP 409)"
   gh api repos/dry-bag/drybag/private-vulnerability-reporting --jq .enabled
   # true
   curl -sS -o /dev/null -w '%{http_code}\n' https://pypi.org/pypi/drybag/json
   # 404 before the first release; from then on 200, with you listed as owner at
   # https://pypi.org/project/drybag/
   ```

   Any other answer stops the release here. A `404` from `dry-bag/drybag-plugin` means section
   3's "The plugin repository" has not been done: do it, then read back again. Once it is done, `gh
   api …/git/ref/heads/main` answers `(HTTP 409)` for the empty repository (measured 2026-10-12,
   on the plugin repository before the rename, the day it was created), and the publisher reads it, or a `404`, as no `main`; any
   other failure there stops the release too. A ruleset that
   lists other patterns leaves the tag step 6 pushes movable; a `release tags` that anyone bypasses
   lets that one move it; a `release tag creation` with no `creation` rule, or with another bypass
   than the admin role, lets somebody else create the tag whose code step 7 runs on your machine; a
   plugin repository whose tags can move, or where a branch can take a tag's name, lets the
   marketplace's `ref` name a tree nobody attested, one where somebody other than the admin role can
   create a release tag lets them take the tag step 7 pushes first, which the publisher can only
   reject (`another commit under the tag`, exit `1`), one whose `main` can be deleted or rewound
   loses the parent the next plugin commit names, and a fifth ruleset there is a line this listing
   does not expect; a plugin repository whose `main` is not the commit this `main`'s marketplace
   pins is one the next release cannot follow (section 5); reporting that is off sends every
   reporter `SECURITY.md` directs to the advisory form back to a public issue; and a PyPI project
   somebody else owns is one step 5's README would tell every reader to install.

   **After a stopped release whose plugin was pushed**, the plugin repository's `main` is that
   release's plugin commit, which only the spent release commit pins, so the `grep` above names
   the plugin commit before it. Read the spent version's tag instead, `vSPENT`, which must name
   that `main`; step 5's `pin` refuses until section 5's restore commit puts it back into the
   entry. After a stopped release whose plugin was not pushed, the three lines agree as they are.

   ```bash
   git show 'vSPENT:.claude-plugin/marketplace.json' | grep '"sha"'
   ```

2. **Decide the version.** This is a judgement, not a command. The first release is `0.1.0`,
   an alpha, and the tree already says so, with "Development Status :: 3 - Alpha". Every
   mechanism in this file works with whatever number you pick — the gate compares the tag to
   the sources rather than to a number it knows — except the alias, which is the major and
   exists from `1.0.0` on (step 9).

3. **Set it in the five places you edit by hand**, then let the lockfile follow:
   `pyproject.toml`, `src/drybag/__init__.py`, both plugin manifests, and the `ref` of the
   plugin entry in `.claude-plugin/marketplace.json`, `vX.Y.Z`.

   ```bash
   uv sync
   uv run python scripts/release.py check   # names every source that still disagrees
   ```

   That is five of the seven sources; `uv.lock` is the sixth and `uv sync` above writes it.
   `CHANGELOG.md` is the seventh and is still behind here; a pending fragment is what lets it
   lag, and step 4 catches it up.

   **And the two example configurations, which a test holds.** `README.md`'s and `docs/cli.md`'s
   example `drybag.toml` blocks each carry `version = "X.Y.Z"`, and a copy of a stale one
   makes `drybag doctor` warn on a brand-new project. `scripts/release.py check` cannot see
   them, because they are examples and not sources, so `tests/test_documents.py` holds them
   instead: it fails until both name the version the tree carries, and the release workflow runs
   the suite on the tag.

4. **Assemble the changelog.** A fragment that names the release's own tag cannot know it and
   spells it `vX.Y.Z`; towncrier copies a fragment's text as it is, so replace each one with the
   tag before `notes` runs (`grep -rn 'vX\.Y\.Z' changelog.d/` finds them).

   ```bash
   uv run python scripts/release.py notes --version X.Y.Z --draft   # read it first; writes nothing
   uv run python scripts/release.py notes --version X.Y.Z
   uv run python scripts/release.py check   # must print "one version everywhere: X.Y.Z"
   ```

   Read what it wrote, and **edit it**. A fragment written as a note to the author rather than
   as a release note is worth fixing now — this is the text users see. The version comes before
   the changelog because `scripts/release.py notes` refuses a `--version` that is not the
   project's; after this step `CHANGELOG.md` carries the heading and `changelog.d/` is empty.
   Four things to look for, in this order:

   - **A fix for something that never shipped.** A `Fixed` entry is a fix *relative to the
     previous release*, so it is honest only if a user of that release could have met the bug,
     and a `Changed` entry only if it changes something that release did. Fragments are the
     per-commit record, so over a development cycle they accumulate fixes to code the same
     cycle introduced; a fold done earlier is undone by the next commit, which is why the check
     belongs here, once, over the assembled file. For each entry, ask whether the code it
     describes was there at the previous tag: `git log --oneline vPREV..HEAD -- <the file it
     touches>` shows whether it arrived after the tag, and `git show vPREV:<path>` shows what
     the released code did, so you can look for the described bug in it. If the bug or the
     behaviour is not there, state the feature as what it now is and delete the fix; keep the
     ones a reader of the previous release has to act on — a grammar that refuses a
     `drybag.toml` which loaded before, a flag that means something narrower than it sounds.
     `scripts/release.py check --tag` cannot judge this: it counts pending fragments and never
     reads them.

     **The first release is this rule with nothing to compare against.** There is no previous
     tag, so every `Fixed` entry in 0.1.0 described a bug no user could have met, and read as a
     warning about the release it shipped in. Fold them all into the features they repair
     (`attach`, `doctor` and `overlay` each accumulated several), and do the same to a
     `Changed` entry that changed something never released.

   - **Lead with what the user sees.** Open each entry with the outcome, then say why or how.
     An entry that opens with the mechanism can be read as meaning the opposite of what it goes
     on to say. When an entry enumerates cases, such as five different refusals, make it a list,
     so a reader can find the one that is theirs.

   - **No internal terms without a user-facing meaning.** A reader of the changelog has not read
     the code. 0.2.0's entries name "the note reader", a "real" configuration file (one that is
     not a symlink), "the session-start line" and "the `preset-rules` and `standing-rules`
     bundle" (the first since removed) without saying what each is to someone using the tool;
     say what the user would see, or say the thing in the words the commands print.

   - **Contract changes are not fixes.** For a 0.x minor, which may break what the one before
     it did, call out what a script or a habit can depend on, because a `Fixed` entry hides
     it: an `upgrading` fragment holds it as a list, one bullet per thing a caller relies on,
     each pointing at its full entry, and the notes render it first, as **Upgrading**. Two of
     0.2.0's sat under `Fixed` and are what that hides: `attach --check` exiting `2`
     instead of `0` for a repository whose `memory.mode` is not `overlay` (`docs/cli.md`
     documents the exit codes as the way a caller tells a finding from a refusal, so a CI
     script that ran it goes red), and `attach` newly writing a marked block into
     `.git/info/exclude`, a file it did not touch before. The third, `reply_language` and
     `artifact_language`, which `setup` still records and nothing reads, is the one 0.2.0 did
     call out, under `Changed`.

5. **Edit the README's install section, then commit.** `README.md`'s Install section names the
   release twice, in **Released as X.Y.Z.** and in the tagged `/plugin marketplace add
   dry-bag/drybag@vX.Y.Z`; set both to the new version. `tests/test_documents.py` fails
   until they name the version the tree carries, and the release workflow runs the suite on the
   tag. Do it now: the commit below is the release commit, and after step 6 the tag points at
   whatever this commit contains.

   **Then pin the plugin commit into it.** `scripts/release.py pin` computes the plugin commit of
   `HEAD` (section 1) and writes it into the marketplace entry's `sha`; amending it in leaves that
   commit as `pin` computed it, because the plugin tree does not hold the marketplace and the
   amend keeps the first parent:

   ```bash
   git commit -am "chore(release): X.Y.Z"
   uv run python scripts/release.py pin
   git add .claude-plugin/marketplace.json && git commit --amend --no-edit
   ```

   A release whose version and changelog moved in `dev`, through a pull request, leaves `-am`
   nothing to commit: make the first command `git commit --allow-empty -m "chore(release): X.Y.Z"`
   and run the other two as written.

   `pin` writes nothing unless the plugin commit's parent is `dry-bag/drybag-plugin`'s `main`
   — the commit section 3 seeds it with, for the first release after the rename, and after it whatever plugin commit was pushed last, a spent
   release's included — because that `main` moves only by fast-forward. Its refusal names both
   commits; section 5 says what each means. It lists `main` with `git ls-remote` through your own
   git, which a `url.*.insteadOf` or a `GIT_CONFIG_*` variable can point elsewhere, so its check is
   the early catch, before any tag is pushed; the publisher's in step 7, which asks GitHub's API,
   is the one that decides. After a stopped release whose plugin was pushed, it refuses naming
   that release's plugin commit as the plugin repository's `main`: make section 5's restore
   commit, then run this step again from its first command.

6. **Tag, twice, and check the tag.** `claude plugin tag` is the platform's own tool: it reads
   the version from `plugin.json` and creates `drybag--vX.Y.Z` here. `vX.Y.Z` is the tag
   `release.yml` triggers on, the one `README.md`'s install paragraph hands a reader
   (`/plugin marketplace add` takes any git ref), and the one the marketplace entry's `ref` pins
   in the plugin repository. Both name the same commit. Nothing in the install path reads the
   `drybag--` tag; it is what the platform's tool makes. `check --tag` computes the plugin
   commit of the tagged commit again and refuses a marketplace entry whose `sha` is another, so
   an edit to the plugin tree after `pin` stops here, before the push.

   **No prerelease tags.** `scripts/release.py check --tag` compares the tag to
   `pyproject.toml`'s literal version string, and `uv.lock` normalises a PEP 440 prerelease
   (`0.1.0-rc1` becomes `0.1.0rc1`), so the seven-source rule cannot be satisfied by an `rc` today.
   `release.yml` triggers on finals only, deliberately.

   **Push the tags, not `main`.** A pending publisher does not reserve the PyPI name: until a
   distribution exists under it anyone may upload one, and the release commit's README already
   tells a reader to `uv tool install drybag`. That text has to be in the release commit,
   because the README is the package's long description and the wheel is built from the tag,
   so what waits is `main`: it moves in step 7, once `publish` has put the name in your hands,
   and not before.

   ```bash
   claude plugin tag .
   git tag vX.Y.Z
   uv run python scripts/release.py check --tag vX.Y.Z
   git push origin vX.Y.Z drybag--vX.Y.Z
   ```

7. **Watch `build` and `attest`, publish the plugin, then approve.** Watch those two jobs, not
   the whole run: the run goes on waiting for the `pypi` approval, and the plugin goes out before
   it.

   ```bash
   gh run list --workflow release --limit 1
   gh run view <id> --json jobs \
     --jq '.jobs[] | select(.name == "build" or .name == "attest") | "\(.name) \(.conclusion)"'
   # build success, then attest success, once each has finished; no conclusion while it runs
   ```

   `build` runs the gate against the tag, the pin included, tests and builds the packages.
   `attest`, which runs no suite and installs nothing, computes the plugin commit of the tag's
   commit with `scripts/plugin_tree.py commit --require-pin`, which fails on a marketplace entry
   pinning another, and attests both the packages and the plugin tree's manifest. Once both are
   green the attestations exist, and before you approve anything, push the plugin, from this
   checkout, with `gh` 2.101.0 or later logged in to `github.com`, and an SSH key GitHub knows:

   ```bash
   uv run python scripts/publish_plugin.py --tag vX.Y.Z          # verify, build, read back, plan
   uv run python scripts/publish_plugin.py --tag vX.Y.Z --yes    # push main and the tag
   ```

   The script reads `gh --version` before any other `gh` call and refuses a `gh` older than
   2.101.0, the version its attestation flags were measured on (upgrade `gh`), and a `gh`
   pre-release (install a released `gh`). It then asks
   `gh auth status --hostname github.com --active`, and checks that GitHub's `dry-bag/drybag`
   names the same commit under the tag as this checkout does before it runs any of the tag's code;
   it builds the plugin commit with the tag's own `scripts/plugin_tree.py`, read out of the tag's
   objects, never this checkout's copy. The commit is the same on every run, so the dry run names
   the commit the `--yes` run pushes, and it is the `sha` the release commit pins.

   The plugin goes first because the release commit's marketplace names `ref: vX.Y.Z` and its
   `sha` in `dry-bag/drybag-plugin`, a tag and a commit that exist there only once this has
   run, and the approval is what makes the PyPI page and the GitHub Release public. Until then
   nothing public points at the tag, and somebody who finds it early gets an install error, not a
   wrong plugin.

   **Its exit code says what to do next**, and a refusal is never worked around — no hand-made
   push, no other checkout, no other remote. Running the command again is safe: nothing is pushed
   before its one atomic push, and a failed atomic push moves no ref.

   - **`0`: published, or ready to be.** `would push …` from the dry run: run it again with
     `--yes`. `pushed …`, or `already published …; nothing was pushed` from a run that finds the
     plugin repository's tag naming the pinned commit, wherever its `main` has moved since:
     approve.
   - **`2`: fix it and run again; the `pypi` approval waits.** Anything that is not a fact of the
     release: a tag that is not `vX.Y.Z`, or not in this checkout; a `gh` older than 2.101.0, a
     `gh` pre-release, or one whose version cannot be read; `gh` not logged in to `github.com`, or
     offline; a local tag that is not GitHub's (push the tags, step 6, when GitHub holds none; when
     GitHub's names another commit, none of its code has run yet, and that tag is investigated
     before anything is fetched or run, because one you did not push is somebody else's, which
     section 3's `release tag creation` exists to refuse; fetch GitHub's over yours with
     `git fetch --tags --force`, which a plain `git fetch --tags` refuses as clobbering your tag,
     only when yours is the stale one: GitHub's names the commit you pushed, and your local tag was
     made again since); SSH or the network failing `git ls-remote`, `fetch` or `push`; a GitHub
     answer that could not be had or read; an attestation that does not verify, below;
     `git ls-remote` disagreeing with GitHub's API, which names a redirect — a `url.*.insteadOf` or
     a `GIT_CONFIG_*` variable — or a `main` that moved while it ran; a push the remote refused,
     which moved nothing, being atomic; a pushed tag GitHub's API does not list, after which the
     publisher lists the tag once with `git ls-remote`: named there at the pushed commit, GitHub
     has not listed it yet (`does not list vX.Y.Z yet; run again`), and a run once it does reports
     it as already published, while a run before that meets `git ls-remote` disagreeing with
     GitHub's API and exits `2` again; not named there at the pushed commit, the push went
     elsewhere, through a `url.*.pushInsteadOf`, a `remote.<url>.pushurl` or a `GIT_CONFIG_*`
     variable, which moves a push and not a listing, so remove it before you run again; a pushed
     tag GitHub lists under another commit, somebody else publishing the same tag at the same
     moment or a redirect again, of the listing or of the push alone, so find which and fix it
     before you run again; and a refusal or a crash of the tag's own `scripts/plugin_tree.py`,
     because CI ran the same code on the same commit green, so a cause on this machine is the
     likely one.

     **A failed `gh attestation verify` is always `2`**, never `1`, and what to do next depends
     on what GitHub's attestation listing answers for the manifest's digest:

     - **`404` or `409`: no attestation of this manifest yet**, so `attest` has not written it.
       Once `build` and `attest` are green, run again; if it says the same then, reject the
       `pypi` approval: `attest` has attested a manifest, and it is not the one the tag's code
       made here from the same commit, so what this run would push is not what was attested.
     - **`200` listing an attestation:** GitHub holds one that does not verify on this machine
       against `dry-bag/drybag`'s `release.yml` at this tag and commit, which a wrong
       attestation and a `gh` or network that cannot verify here both look like. Run again; if it
       says the same with a working `gh` and network, once `build` and `attest` are green, reject
       the `pypi` approval.
     - **Any other answer:** run again.

     A rejection after a repeat is your decision on a repeated `2`, not an exit `1`: the
     refusal's own words may end `reject the release's approval`, conditionally and in lower
     case, and the exit code is what classifies it.
   - **`1`: reject the `pypi` approval.** A fact of the release that no re-run changes, said in a
     refusal that ends `Reject the release's approval`: the tag's marketplace does not pin the
     plugin commit its own tree makes; the tag's `.claude-plugin/plugin.json` names another
     version; the commit built for the tag reads back as another tree; GitHub's plugin repository
     holds another commit under the tag; or its `main` is not the plugin commit's parent, a
     release commit cut on the wrong base (section 5). The tags are spent while nothing else is
     (section 5). The first two are found before the attestation is asked about, and are not
     waiting on it: the tag's own code finds them on the commit GitHub's tag names, and no
     attestation changes what that commit's tree makes or what its `plugin.json` says.

   A run against another `--remote` than the default (a scratch repository, a rehearsal) is
   classified from `git ls-remote` alone, reads nothing back after its push, and its summary, like
   a rejection resting on that listing, says `not confirmed through GitHub's API`. The default is
   `git@github.com:dry-bag/drybag-plugin.git`, and
   `https://github.com/dry-bag/drybag-plugin.git`, spelled exactly, counts as it too.

   Then approve `pypi`. **Once section 3's `pypi` environment exists with a required reviewer**,
   `publish` and `github-release` both wait for it. An approval is given per environment, not
   per job, so one approval starts both and one rejection stops both; `github-release` does not
   depend on `publish`, so a failed upload still leaves you a Release. **An approval given early
   uploads nothing:** each of the two jobs first lists the plugin repository's tag and fails,
   before it downloads or uploads anything, unless the tag names the plugin commit `attest`
   computed; publish the plugin, then re-run the two (`gh run rerun <id> --failed`), and approve
   `pypi` again if GitHub asks: both name that protected environment, and a re-run job may wait
   for its approval as the first run did, so read the run's page rather than assume either way.
   Without that environment both jobs run straight through the name GitHub invents for them, and
   nothing on this tag waits for a human. Watch the rest of the run:

   ```bash
   gh run watch <id> --exit-status
   ```

   When `publish` is green and `https://pypi.org/project/drybag/` lists you as owner, move
   `main` to the release commit:

   ```bash
   git push origin main
   ```

   If `publish` failed because the name was taken in the meantime, `github-release` has still
   published a Release whose README tells readers to install that name. Delete the Release
   (`gh release delete vX.Y.Z`), leave `main` where it is, still saying nothing is released,
   and settle the name with PyPI before anything else. The tags cannot be removed (section 5).

8. **Publish the overlay template**, from this checkout, with an authenticated `gh` and an SSH
   key GitHub knows:

   ```bash
   uv run python scripts/publish_template.py --owner dry-bag       # read the plan
   uv run python scripts/publish_template.py --owner dry-bag --yes  # do it
   ```

   Without `--yes` nothing outward-facing happens: it renders, asks `gh` what is there, and
   reports what it would create, mark and push. It is this repository's script and no command
   drybag ships, since only a publisher publishes the template; an owner's
   `drybag setup --overlay create:` generates from it.

9. **Move the alias — from `1.0.0` on; a `0.x` release moves none.** The alias is the major:
   a reference to `@v1` takes every release the alias moves to. Under semantic versioning a
   `0.x` minor may break what the one before it did, so a `v0` alias would hand everything that
   references it breaking changes unannounced, and this step starts at the first `1.x` release:

   ```bash
   git tag -f v1 vX.Y.Z && git push -f origin v1
   git ls-remote origin refs/tags/v1 refs/tags/vX.Y.Z   # both lines name one commit
   ```

   The alias resolves as any tag does; what is left to check is that it names the release, and
   the listing above is that check.

## 3. One-time setup

**Trusted Publishing.** The workflow authenticates to PyPI with a short-lived OIDC token rather
than a stored secret, which requires a one-time registration on PyPI:

**PyPI → Your projects → drybag → Publishing → Add a new publisher (GitHub)**

| Field | Value |
|---|---|
| Owner | `dry-bag` |
| Repository | `drybag` |
| Workflow | `release.yml` |
| Environment | `pypi` |

For the very first release, before the project exists on PyPI, use PyPI's **pending publisher**
form instead — same fields, reached from your account's publishing settings.

**The `pypi` environment — before the first tag, not after it.** Create it in **GitHub →
Settings → Environments**, and add yourself as a required reviewer. That is the last human
gate, and both `publish` and `github-release` wait behind it: a tag pushed by mistake waits
for an approval instead of becoming a permanent PyPI release or a public GitHub Release.
PyPI does not allow re-uploading a version. **Create it first**: naming an environment that
does not exist does not fail the job — GitHub creates one on the spot, with no protection
rules — so a release cut before this step would have the gate's two `environment:` lines and
none of the gate.

This paragraph is no longer the whole of the defence. `release.yml`'s `environment-gate` job
reads the environment's protection-rule count over the API before either gated job can start,
and fails the run when it is zero: the order these two sections are written in is now checked
rather than asked for. If the workflow's own token cannot read
`GET /repos/OWNER/REPO/environments/NAME` — the endpoint is not open to every default token —
the gate refuses by default, and the way to say "it is a real gate, the read is simply closed
to me" is a repository variable, **Settings → Secrets and variables → Actions → Variables**,
`PYPI_ENVIRONMENT_PROTECTED = true`. It stands in for the *read* only: an environment that
reads back with zero rules fails whatever the variable says. Set it only after the environment
and its reviewer exist.

**Tag protection.** Two repository rulesets over `refs/tags/v*.*.*` and
`refs/tags/drybag--v*`, both leaving the `v1` alias, once a `1.x` release creates it — it
matches neither pattern — free to move:

- `release tags`, with `deletion` and `update` rules and no bypass, so a semver tag is
  immutable for everyone, you included.
- `release tag creation`, with a `creation` rule that the repository's admin role bypasses, so
  nobody else can create such a tag. Step 7's publisher runs the code of the tag it is given once
  GitHub names the same commit under it as your checkout does, so a tag somebody else created first
  is one whose code a fetch over yours would have it run. The bypass is the body's `bypass_actors`,
  where `RepositoryRole` `5` is the admin role.

GitHub's REST reference does not name the built-in roles' ids, and step 1's read-back only echoes
the id it was given; the settings page showed `5` as **Repository admin** on both repositories, before
the rename, on 2026-10-12. So after creating such a ruleset anew, here or in the plugin repository below, open it
under **Settings → Rules → Rulesets** and confirm that its bypass list reads **Repository admin**;
any other role there is the one that can create a release tag.

Two rulesets, not one, because a ruleset's bypass applies to every rule it carries: a bypass on
`release tags` would let an admin move or delete a published tag. The same body creates each
ruleset or, when one of that name already exists, replaces it in place; a second `POST` beside an
existing one would leave two rulesets and fix neither:

```bash
cat > "${TMPDIR:-/tmp}/release-tags.json" <<'JSON'
{"name": "release tags", "target": "tag", "enforcement": "active",
 "conditions": {"ref_name": {"include": ["refs/tags/v*.*.*", "refs/tags/drybag--v*"], "exclude": []}},
 "rules": [{"type": "deletion"}, {"type": "update"}]}
JSON
cat > "${TMPDIR:-/tmp}/release-tag-creation.json" <<'JSON'
{"name": "release tag creation", "target": "tag", "enforcement": "active",
 "conditions": {"ref_name": {"include": ["refs/tags/v*.*.*", "refs/tags/drybag--v*"], "exclude": []}},
 "rules": [{"type": "creation"}],
 "bypass_actors": [{"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"}]}
JSON
release_ruleset() {  # $1 a ruleset's name, $2 its body: replace the one of that name, or create it
  id=$(gh api repos/dry-bag/drybag/rulesets --jq ".[] | select(.name == \"$1\") | .id")
  if [ -n "$id" ]; then
    gh api -X PUT "repos/dry-bag/drybag/rulesets/$id" --input "$2"
  else
    gh api -X POST repos/dry-bag/drybag/rulesets --input "$2"
  fi
}
release_ruleset "release tags" "${TMPDIR:-/tmp}/release-tags.json"
release_ruleset "release tag creation" "${TMPDIR:-/tmp}/release-tag-creation.json"
```

Then read the two back with section 2's step 1, one line each.

**The plugin repository.** Before the first `scripts/publish_plugin.py --yes`, create
`dry-bag/drybag-plugin`, public and empty — no README, licence or `.gitignore` — then seed it and
protect its tags and its `main`. The seed is the commit the first release's plugin commit follows, the
`sha` `.claude-plugin/marketplace.json` pins, which is the last plugin commit pushed before the rename:
from a clone of the plugin repository the earlier releases were published from, `git push
git@github.com:dry-bag/drybag-plugin.git f6d299144481ccc0824c890913985abc16e0bc6f:refs/heads/main`.
Without the seed `pin` refuses, since the new plugin commit has that parent and the repository has no
`main`. A
ruleset applies every rule it carries to every ref it matches and has one target, tags or
branches, and its bypass applies to every rule it carries, so four rulesets: `release tags`, with
`deletion` and `update` rules over `refs/tags/v*.*.*` and no bypass, so a published tag never
moves; `release tag creation`, with a `creation` rule over the same pattern that the admin role
bypasses, as this repository's does, so nobody else can create the tag step 7 pushes before you
do — the publisher compares ids, and a tag somebody else created there first is one it can only
reject (`another commit under the tag`, exit `1`), spending the version; `no tag-shaped
branches`, with a `creation` rule over `refs/heads/v*`, so no branch can take a tag's name and
shadow it; and `main`, with `deletion` and `non_fast_forward` rules over `refs/heads/main`, so the
commit each release's plugin commit names as its parent stays where the next one finds it. None
of them refuses your first push, which creates `main` and a tag the admin role may create. The
same create-or-replace as above, with the repository name changed:

```bash
gh repo create dry-bag/drybag-plugin --public \
  --description "The drybag plugin, generated from dry-bag/drybag at each release"
cat > "${TMPDIR:-/tmp}/plugin-release-tags.json" <<'JSON'
{"name": "release tags", "target": "tag", "enforcement": "active",
 "conditions": {"ref_name": {"include": ["refs/tags/v*.*.*"], "exclude": []}},
 "rules": [{"type": "deletion"}, {"type": "update"}]}
JSON
cat > "${TMPDIR:-/tmp}/plugin-release-tag-creation.json" <<'JSON'
{"name": "release tag creation", "target": "tag", "enforcement": "active",
 "conditions": {"ref_name": {"include": ["refs/tags/v*.*.*"], "exclude": []}},
 "rules": [{"type": "creation"}],
 "bypass_actors": [{"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"}]}
JSON
cat > "${TMPDIR:-/tmp}/plugin-tag-shaped-branches.json" <<'JSON'
{"name": "no tag-shaped branches", "target": "branch", "enforcement": "active",
 "conditions": {"ref_name": {"include": ["refs/heads/v*"], "exclude": []}},
 "rules": [{"type": "creation"}]}
JSON
cat > "${TMPDIR:-/tmp}/plugin-main.json" <<'JSON'
{"name": "main", "target": "branch", "enforcement": "active",
 "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
 "rules": [{"type": "deletion"}, {"type": "non_fast_forward"}]}
JSON
ruleset() {  # $1 the ruleset's name, $2 its body: replace the one of that name, or create it
  id=$(gh api repos/dry-bag/drybag-plugin/rulesets --jq ".[] | select(.name == \"$1\") | .id")
  if [ -n "$id" ]; then
    gh api -X PUT "repos/dry-bag/drybag-plugin/rulesets/$id" --input "$2"
  else
    gh api -X POST repos/dry-bag/drybag-plugin/rulesets --input "$2"
  fi
}
ruleset "release tags" "${TMPDIR:-/tmp}/plugin-release-tags.json"
ruleset "release tag creation" "${TMPDIR:-/tmp}/plugin-release-tag-creation.json"
ruleset "no tag-shaped branches" "${TMPDIR:-/tmp}/plugin-tag-shaped-branches.json"
ruleset "main" "${TMPDIR:-/tmp}/plugin-main.json"
```

Then read the four back with section 2's step 1, whose listing names each of them on a line of
its own, and confirm `release tag creation`'s bypass on its settings page as above; any other
answer is a repository to fix before anything is pushed to it.

**Private vulnerability reporting.** `SECURITY.md`, `CODE_OF_CONDUCT.md` and both issue-template
files send reporters to the advisory form, which exists only while the repository setting is on:

```bash
gh api -X PUT repos/dry-bag/drybag/private-vulnerability-reporting
```

**A conduct contact address.** `CODE_OF_CONDUCT.md` still routes a report through the security
advisory form. That is worth a real address before the repository is advertised.

## 4. The harness CLI version

`.github/workflows/ci.yml` and `.github/workflows/smoke.yml` each `npm install -g
@anthropic-ai/claude-code@<version>` — the validator the first one runs and the installer the
second one runs are the same tool, and the two pins must move together. A global npm install is
not a manifest, so Dependabot does not see either of them: bump both by hand, in one commit,
and let the smoke run say whether an install still works.

**The overlay template's own action pins.** `src/drybag/templates/overlay/.github/workflows/scan.yml`
pins two actions by full-length sha, and this repository's `.github/dependabot.yml` scans
`.github/workflows/` at the root and nothing else — a nested tree under `src/` is not a
workflow directory the platform reads, so those two pins rot here until somebody looks.
The same file's `GITLEAKS_VERSION` and the `rev:` of the template's `.pre-commit-config.yaml`
(a sha, with its release in a `# frozen:` comment) are not action pins at all, so no configured
Dependabot sees them (it has a `pre-commit` ecosystem, which neither `dependabot.yml` sets up):
bump them by hand, to one gitleaks release, in one commit.
`tests/overlay/test_template.py` holds the two equal.
A rendered overlay ships its own `dependabot.yml` and keeps itself current from then on;
what this line is about is the state every *new* overlay starts from. Check them here, at
the release that publishes the template.

## 5. If something goes wrong

- **Anything goes wrong after the tags are pushed.** The ruleset refuses to delete or move a
  pushed `vX.Y.Z` or `drybag--vX.Y.Z`, for everyone, so that version is spent whether or not
  anything was published: a wrong tag, a red `build`, a rejected approval or a failed upload.
  A red `attest` that failed for a transient Sigstore or attestation-service error is not one:
  re-run that job (`gh run rerun <id> --failed`), which computes the same plugin commit of the
  same tag and attests the same files.
  `main` was not pushed, so nothing else needs undoing. Cut X.Y.(Z+1) from step 1, on the
  commit "Which commit a release is cut on", below, names: step 1 leaves the spent release commit
  behind, so steps 3 and 4 set the new version and assemble the changelog again. If a Release was
  created for the spent version, delete it, as step 7 says for a taken name.
- **Which commit a release is cut on.** Always `origin/main`, as step 1 leaves it. A release
  commit's first parent decides its plugin commit's parent (section 1), and the plugin
  repository's `main` must be that parent, so:
  - **`0.3.0`**, the first release published from a plugin repository, before the rename, was cut
    on `main` once `dev` was merged into it. `main` before that merge still held the marketplace
    entry `"source": "./"`, which `scripts/plugin_tree.py` refuses to read a pin from, since the
    entry's `source` is not an object; the merge brought `dev`'s `url` entry, which pinned no
    `sha`, so the first plugin commit had no parent, as the plugin repository's absent `main`
    required.
  - **Any later release** is cut on `main` once `dev` is merged into it, since `dev` carries the
    `sha` of the plugin commit pushed last ("How a release returns to `dev`", below).
  - **After a stopped release**, on `origin/main` too, never on the spent release commit, which
    its tags keep and step 1's `git switch -C` leaves behind. A fix merged into `origin/main`
    since is then in the release, and step 7's `git push origin main` is a fast-forward. The
    `changelog.d/` fragments the spent commit consumed are pending there again, so step 4's
    `notes` assembles them under the new version, and `CHANGELOG.md` never carries the spent
    one's heading. A release prepared in `dev` consumed them there instead, and `dev` holds the spent
    heading: a pull request into `dev` moves the version and that heading before step 1, and step 4
    has nothing to assemble. Step 5 runs as written. If `pin` refuses because the plugin repository's
    `main` is the spent release's plugin commit, which no commit on `origin/main` pins, the
    spent release's plugin was pushed: make the restore commit ("How a release returns to
    `dev`", below), then run step 5 again from its first command.

  `pin` says which, before any tag is pushed: its refusal names the parent the plugin commit has
  and the commit the plugin repository's `main` holds, and `git ls-remote
  https://github.com/dry-bag/drybag-plugin.git refs/tags/vSPENT` lists the spent version's
  tag there when its plugin was pushed. A patch release of an older line, `0.3.1` after `0.4.0`,
  is not supported: its plugin commit's parent is not the plugin repository's `main`, so `pin`
  refuses it, and so would the publisher.
- **How a release returns to `dev`.** Once the release is out, branch `chore/after-release-X.Y.Z`
  from `main`, the release commit, and merge it into `dev` through a pull request. `dev`'s
  marketplace then pins the release's `sha`, and the next `dev` → `main` merge brings it back to
  `main`, where the next release commit's first parent pins it. A merge into `main` that resolved
  `.claude-plugin/marketplace.json` to a `dev` copy pinning another `sha` loses it: a copy pinning
  none gives the next plugin commit no parent, and `pin` refuses it with no parent while the plugin
  repository's `main` exists; a copy pinning an older one, as `dev` does after a stopped release
  whose plugin was pushed, gives it that older parent, and `pin` refuses it the same way, naming
  both. Nothing is spent yet, since `pin` runs before the tags: put the commit the plugin
  repository's `main` holds — the plugin commit pushed last, a spent release's if one stopped after
  its push — back into the entry, in a commit of its own beneath the release commit, and make the
  release commit again:

  ```bash
  git reset --soft HEAD^   # the local release commit, undone; its edits stay staged
  git ls-remote https://github.com/dry-bag/drybag-plugin.git refs/heads/main
  # set the entry's "sha" in .claude-plugin/marketplace.json to the commit that printed, then:
  git commit -m "chore: restore the plugin pin" -- .claude-plugin/marketplace.json
  ```

  The path-limited commit takes the marketplace alone, with the `ref` step 3 set, and leaves the
  release's other edits staged; step 5 then runs again from its first command. That commit alone
  is red under plain `check`, its `ref` naming the new version while every other source names the
  old one, and nothing checks it alone: it is never tagged, and `git push origin main` in step 7
  runs CI on the release commit above it.
- **The plugin push was refused or failed.** `scripts/publish_plugin.py` pushes `main` and the
  tag together, atomically, and only after the attestation and the read-back held, so a refusal
  or a failed push leaves the plugin repository as it was, and this repository's `main` and the
  `pypi` approval where they were. Step 7 says, by its exit code and its words, when to run it
  again and when to reject the approval. A plugin tag that was pushed is spent like this
  repository's: its ruleset refuses to move or delete it, and the next release is X.Y.(Z+1). A
  push that went through for a release that then stopped — a rejected approval, a failed upload —
  stays, beside the spent tag of this repository that names it: `main` here still installs the
  previous release, but the spent `dry-bag/drybag@vX.Y.Z` still installs that plugin, because
  its marketplace's `ref` and `sha` resolve. The next release is cut on `origin/main` all the
  same, and its restore commit pins that plugin commit, so the next one follows it ("Which commit
  a release is cut on", above).
- **PyPI published a bad release.** You cannot replace it. Yank it on PyPI (which hides it from
  resolvers without breaking anyone who has already pinned it) and release a patch version.
- **`scripts/release.py check` fails in the workflow but passed locally.** Almost always
  `uv.lock`: `uv sync` was not run after the version bump, so the lockfile still carries the old
  one.
- **`scripts/publish_template.py` pushed the wrong tree.** Its next run fixes it: it replaces the
  tree whole rather than merging into it.

## 6. The release scripts

`scripts/release.py` is this repository's own tooling, not a command drybag ships: it only
ever checked the drybag repository itself. It runs through the same frame as the CLI, so
`--json` is accepted anywhere on the line before a bare `--` and prints one object, and it exits `0` on success,
`1` on findings and `2` on a refusal.

```bash
uv run python scripts/release.py check [--tag TAG]               # one version everywhere
uv run python scripts/release.py notes --version X.Y.Z [--draft]  # assemble CHANGELOG.md
uv run python scripts/release.py pin [--remote URL]               # the plugin commit, pinned
```

**`check`** cross-checks the seven sources of section 1 and exits `1` naming every one that
disagrees. Its `--json` object carries `summary`, `versions` (every source and what it says) and
`problems` (empty on a clean run), and it carries all three whether or not there is drift — the
drift is in `problems`, not in the shape. A source it cannot parse at all is still a failure and
prints `error` instead. `--tag` accepts both tag shapes, `vX.Y.Z` and `drybag--vX.Y.Z`, because
either may be the ref a run was created from. Under `--tag`, once it finds the marketplace entry
well-formed, it also runs `scripts/plugin_tree.py commit` on `HEAD` (an entry it finds malformed is
reported once, as the entry's finding, and the rest is asked once it is fixed), and refuses a plugin
tree past the 512 files the plugin directory lists unheld (section 2), a marketplace entry that pins
no `sha` or another commit than the plugin commit that tree makes (the `plugin pin` finding, which
names the commit and, for an entry pinning none, says to run `pin`), and a tree that script could
not read, quoting what it said — a clone without `HEAD`'s first parent among them, which it names
`fetch-depth: 2` for. Plain `check`, which CI runs on every pull request, never counts and never
computes the commit, because `tests/test_payload.py` holds the same count there and the pin is the
release commit's alone. It writes nothing; it reads the sources, the fragments pending in
`changelog.d/`, and under `--tag` the committed tree.

**`notes`** is a wrapper around towncrier, which does the rendering while `[tool.towncrier]` in
`pyproject.toml` owns the format. A `--version` that is not the project's is refused (`2`) before
towncrier runs, because assembling under another number writes a `CHANGELOG.md` heading that
`check` then refuses; a towncrier that cannot be run is a finding (`1`) naming it as the
development dependency it is. Without `--draft` it writes `CHANGELOG.md` and consumes the
fragments: towncrier removes each one from `changelog.d/` and, in a git checkout, stages both
changes — `git add` of `CHANGELOG.md`, `git rm` of each tracked fragment, which removes the
directory itself when the tracked fragments were all it held. With `--draft` it writes nothing
and prints the rendered section.

**`pin`** is step 5's command: it computes the plugin commit of `HEAD` with
`scripts/plugin_tree.py commit` and writes it into the marketplace entry's `sha`, once it has
listed the plugin repository's `main` (`--remote`, by default
`https://github.com/dry-bag/drybag-plugin.git`, only ever listed) and found it the commit's
parent. Everything it refuses, it refuses before writing: a tree that script cannot make the
commit of, a marketplace on disk that cannot take the `sha`, a remote that cannot be listed, and a
`main` that is not the parent (section 5). Two runs write the same file.

**`scripts/plugin_tree.py`** names the plugin's nine paths once, in `PLUGIN_PATHS`, reads them
from a commit and never from the disk, and writes the manifest a release attests and the plugin
commit a release pins, `--no-parent` only ever for a scratch repository; its module docstring
and `--help` are its reference.

```bash
uv run python scripts/plugin_tree.py manifest --root . --rev HEAD [--exact] [--manifest-file FILE]
uv run python scripts/plugin_tree.py render --root . --rev HEAD --out DIR [--manifest-file FILE]
uv run python scripts/plugin_tree.py commit --root . --rev HEAD --git-dir DIR \
  [--manifest-file FILE] [--no-parent] [--require-pin]
```

**`scripts/publish_plugin.py`** is step 7's command, which builds the plugin commit a tag pins
with that tag's own code, verifies its attestation, and pushes it to the plugin repository as
`main` and the tag, atomically, only under `--yes`; its module docstring and `--help` are its
reference, and step 7 its exit codes.

```bash
uv run python scripts/publish_plugin.py --tag vX.Y.Z [--remote URL] [--yes]
```

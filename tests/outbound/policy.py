"""What stayfixed's launches may reach, declared: the policy `tests/test_outbound.py` holds the
package to, over what `tests/outbound/walk.py` finds.

The classification tables and the declarations are held both ways: a launch no entry accounts
for is a finding, and so is an entry no launch uses, because a declaration about nothing is
ready to excuse the next launch that matches it. The forbidden modules are held one way, since
nothing may import them, and a root launcher that named nothing would leave its own launch
unread, which is a finding too.
"""

from __future__ import annotations

from tests.outbound.walk import RUNNER, RUNNER_METHOD, Launcher

# Every standard-library module that gives a process a connection of its own. A listed module
# matches with everything below it (`asyncio.streams` is `asyncio`'s), and never by its root alone:
# `urllib`, `http` and `logging` are not listed, because `urllib.parse`, `http.HTTPStatus` and a
# plain logger reach nothing, while `urllib.request`, `http.client`, `logging.handlers` and
# `logging.config` (whose `listen()` opens a socket) do. `asyncio` is listed whole although most of
# it reaches nothing: its connection calls and its subprocess calls come in through one import,
# which a match on names cannot tell apart, and the package imports it for neither. A module that
# wants it for a subprocess is an edit here that says so, and the launches it makes are walked
# like any other. `smtpd`, `asyncore` and `asynchat` are gone from 3.12 and importable on the 3.11
# floor; `_socket` and `_ssl` are what `socket` and `ssl` are built on.
NETWORK_MODULES = frozenset(
    {
        "_socket",
        "_ssl",
        "asynchat",
        "asyncio",
        "asyncore",
        "ftplib",
        "http.client",
        "http.server",
        "imaplib",
        "logging.config",
        "logging.handlers",
        "multiprocessing.connection",
        "multiprocessing.managers",
        "nntplib",
        "poplib",
        "smtpd",
        "smtplib",
        "socket",
        "socketserver",
        "ssl",
        "telnetlib",
        "urllib.request",
        "urllib.robotparser",
        "webbrowser",
        "wsgiref.simple_server",
        "xmlrpc.client",
        "xmlrpc.server",
    }
)
# Every standard-library module that starts a process through no launcher the walk knows, so that
# importing one is a finding rather than a launch to read: `ctypes` (and `_ctypes`, which it is
# built on) can call the C library's `system` or `execv` directly, and `_posixsubprocess` and
# `_winapi` hold the calls `subprocess` itself is built on.
NATIVE_MODULES = frozenset({"_ctypes", "_posixsubprocess", "_winapi", "ctypes"})

# The package launchers the walk starts from, by `(file, function)`; every other is derived from
# them and from the standard library's. Neither of these two can be derived. `gitenv._ask`, the
# one place a `git` is started and the call `git_run` and `git_answer` forward to, puts
# `-C <root>` between `git` and its caller's arguments, and the walk does not read `str(root)`;
# declared, it is taken for what it is, `git` run in the directory `root` names. The real
# `Runner`'s `.launch` is a method, which no import binds: the walk knows each call to it,
# `<receiver>.launch(argv, cwd)`, by the attribute alone, and its own launch is the argv each of
# those hands it.
ROOT_LAUNCHERS: dict[tuple[str, str], Launcher] = {
    ("src/stayfixed/gitenv.py", "_ask"): Launcher(("git",), at=1, spread=True),
    ("src/stayfixed/runner.py", f"_SubprocessRunner.{RUNNER_METHOD}"): RUNNER,
}

# Where each program a launch runs can reach, by the argv prefix that decides it, git's global
# options taken out: the README row that declares it, by the row's first code span. A launch whose
# prefix is here is the row's whatever follows the prefix, because the row discloses the program
# and not one form of it — except a prefix in `USER_COMMANDS`.
NETWORK: dict[tuple[str, ...], str] = {
    ("gh",): "gh",
    ("git", "clone"): "git clone",
    ("git", "fetch"): "git fetch",
    ("git", "ls-remote"): "git ls-remote",
    ("claude", "plugin"): "claude plugin",
    ("codex", "plugin"): "codex plugin",
    ("pre-commit", "install"): "pre-commit install",
    ("sh", "-c"): "sh -c",
}
# The prefixes whose row is the user's own command, which stayfixed does not choose: `sh -c` runs
# the command `test attribute --command` names. Such a launch is its row only when the element
# after the prefix is unread — the user's value; a script the package spells out itself is
# stayfixed's choice, and a finding.
USER_COMMANDS = frozenset({("sh", "-c")})
# The programs a launch runs that reach nothing past this machine, by argv prefix, each as narrow
# as the subcommand's other forms require: `git remote` and `git worktree` have forms that ask a
# remote or change one, and `git config` has forms that write a setting a later launch obeys, so
# only the forms in use are listed. A launch is local only when every element before its options
# end is read, or vouched for in `VOUCHED_ELEMENTS`, none is in `GIT_REMOTE_OPTIONS`, and none is
# among its subcommand's `GIT_PROGRAM_OPTIONS`. A launch in neither table is a finding: it has to
# be read and put in one.
LOCAL = frozenset(
    {
        ("git", "--version"),
        ("git", "archive"),
        ("git", "cat-file"),
        ("git", "check-ignore"),
        ("git", "check-ref-format", "--branch"),
        ("git", "config", "--get"),
        ("git", "config", "--type=path", "--get"),
        ("git", "diff"),
        ("git", "grep"),
        # Without `-w` it writes nothing: the empty tree's id, from an empty standard input.
        ("git", "hash-object", "-t", "tree", "--stdin"),
        ("git", "init"),
        ("git", "log"),
        ("git", "ls-files"),
        ("git", "ls-tree"),
        ("git", "merge-base"),
        ("git", "remote", "get-url"),
        ("git", "rev-list"),
        ("git", "rev-parse"),
        ("git", "show-ref"),
        ("git", "status"),
        ("git", "symbolic-ref"),
        ("git", "version"),
        ("git", "worktree", "list"),
        ("tar", "-xf"),
    }
)
# Local only as the whole argv: `git remote` alone lists the remotes' names, and anything after it
# is a form to read first.
LOCAL_WHOLE = frozenset({("git", "remote")})
# The global options a launch may put before git's subcommand, and whether each takes the next
# argument as its value. None of them changes which program git runs or where it reaches, except
# `-c`, whose value is configuration: it is held to `GIT_CONFIG_KEYS`. Any other option there is a
# finding, because the subcommand the tables match would then follow something unread.
# `--no-optional-locks` keeps a `status` from writing the index it refreshes.
GIT_GLOBAL_OPTIONS = {"-c": True, "--literal-pathspecs": False, "--no-optional-locks": False}
# The configuration a launch may set with `git -c`: each changes how git prints a name, and never
# what it runs or where it reaches, as `core.sshCommand`, `core.fsmonitor` or
# `url.<base>.insteadOf` would.
GIT_CONFIG_KEYS = frozenset({"core.quotePath"})
# Options with which a git command that otherwise reads the local repository asks a remote instead
# (`git archive --remote=<url>`). Wherever one appears before the options end, the launch is not
# local. Matched by the start of the whole name, since `git archive` takes neither of its two
# abbreviated: `--rem=<url>` exits 128 ("Unexpected option --remote"), and beside `--remote` an
# abbreviated `--exec` is handed to the remote side, which refuses it. `--exec` names a program only
# beside `--remote`, which is matched already, so for `archive` it is redundant and costs nothing.
# The other two are options of subcommands that reach a remote whatever they are given.
GIT_REMOTE_OPTIONS = ("--remote", "--upload-pack", "--receive-pack", "--exec")
# Options with which a local git subcommand runs a program: `grep -O` opens the matches in one,
# `--textconv` runs a configured conversion and `--ext-diff` an external diff, either of which can
# fetch, as Git LFS's does, and `cat-file --filters` runs the smudge filters `archive` does. By
# subcommand, since an option means something else under another one: `git diff -O<file>` orders
# its output. Each is matched as git parses it. A long one matches by any prefix of its name, since
# git takes a prefix for the one option it begins (`grep --open-files-in=echo` is
# `--open-files-in-pager`, `grep --textc` is `--textconv`); a prefix that begins two options, or
# names another option whole (`grep --text`, `cat-file --filter=<spec>`), matches as well, which
# refuses what git refuses in the first case and what it would allow in the second, until a launch
# needs it. `diff` and `log` take no prefix at all, so one matched there refuses only what git
# refuses. A short one matches anywhere in a cluster of short options, since git reads `-lOecho`
# as `-l -Oecho`; that matches the `O` of `-eO` too, a pattern git reads as `-e`'s value, so the
# match can refuse what git would allow and never the reverse.
GIT_PROGRAM_OPTIONS: dict[str, tuple[str, ...]] = {
    "grep": ("-O", "--open-files-in-pager", "--textconv"),
    "cat-file": ("--filters", "--textconv"),
    "diff": ("--ext-diff", "--textconv"),
    "log": ("--ext-diff", "--textconv"),
}

# The rows of a launch that reaches nothing past this machine.
NO_ROWS: frozenset[str] = frozenset()
# Each launch the walk does not classify by its argv, and the README rows it can reach: its first
# unread element is declared here, whether that is its program or, as in `unhidden_by_owner`'s
# `git *asked`, the rest of an argv whose program is read. A launch is keyed by `(file, function,
# element)`, the element being that unread element's source text: not by its line, so an edit
# above it leaves the entry true, and not by its function alone, so a launch handing a different
# expression in the same function is a finding. An entry covers an element only while every name
# in it is bound once in its function and never mutated, so the same expression handed again after
# a rebinding is a finding too. The comment says what each runs; a reviewer reads it.
PASS_THROUGH: dict[tuple[str, str, str], frozenset[str]] = {
    # A project's own `[gates.custom.<name>] run`, launched as configured.
    ("src/stayfixed/assess/gates.py", "_custom.run", "list(argv)"): frozenset({"[gates.custom]"}),
    # The test command typed after `stayfixed prove --`, as the runner adapter that recognised it
    # planned it: the command's own words, with the runner's report put where `prove` reads it.
    ("src/stayfixed/prove/run.py", "_launch", "list(plan.argv)"): frozenset({"stayfixed prove --"}),
    # `claude plugin marketplace add` and `codex plugin marketplace add`, then `claude plugin
    # install` and `codex plugin add`, each built by a lambda in `_MARKETPLACE_ADD` or
    # `_PLUGIN_INSTALL`, which `test_the_plugin_installs_reach_the_rows_their_entries_name` calls.
    ("src/stayfixed/setup/run.py", "_install_plugins", "add_argv_of(source)"): frozenset(
        {"claude plugin", "codex plugin"}
    ),
    ("src/stayfixed/setup/run.py", "_install_plugins", "argv"): frozenset(
        {"claude plugin", "codex plugin"}
    ),
    # `claude plugin marketplace add <render directory> --scope local`, then `claude plugin install
    # overlay-<id>@stayfixed-delivery-<id> --scope local`, each `attach.render`'s table with its
    # slot filled, which `test_the_rendered_plugins_install_reaches_the_rows_its_entries_name`
    # fills.
    (
        "src/stayfixed/attach/write.py",
        "_install",
        "filled(PLUGIN_MARKETPLACE_ADD_LOCAL, str(delivery_directory(id)))",
    ): frozenset({"claude plugin"}),
    (
        "src/stayfixed/attach/write.py",
        "_install",
        "filled(PLUGIN_INSTALL_LOCAL, f'{plugin_name(id)}@{marketplace_name(id)}')",
    ): frozenset({"claude plugin"}),
    # `claude plugin uninstall overlay-<id>@stayfixed-delivery-<id> --scope local`, then `claude
    # plugin marketplace remove stayfixed-delivery-<id>`, `detach`'s withdrawal of the same plugin,
    # each where the main checkout's settings file names it, filled the same way.
    (
        "src/stayfixed/attach/write.py",
        "_withdraw_plugin",
        "filled(PLUGIN_UNINSTALL_LOCAL, plugin)",
    ): frozenset({"claude plugin"}),
    (
        "src/stayfixed/attach/write.py",
        "_withdraw_plugin",
        "filled(PLUGIN_MARKETPLACE_REMOVE, marketplace_name(id))",
    ): frozenset({"claude plugin"}),
    # `git [-c core.excludesFile=…] --git-dir=… --work-tree=<empty> check-ignore --no-index
    # --stdin -z`, assembled in `asked`: the owner's own exclude files, asked about.
    ("src/stayfixed/attach/exclude.py", "unhidden_by_owner", "*asked"): NO_ROWS,
    # The overlay's own pinned gitleaks build, found through pre-commit's database and run on
    # `git --pre-commit --staged`, `git --log-opts` or `stdin`: it reads the repository and its
    # input and reaches no network, and a path that is not an executable build is never run.
    ("src/stayfixed/sync/scan.py", "_scan", "str(binary)"): NO_ROWS,
    # `hooks/run-hook.sh --version` under the plugin root this process derived: stayfixed's
    # own hook wrapper, asked for its version.
    ("src/stayfixed/doctor/checks.py", "_wrapper", "str(root / WRAPPER)"): NO_ROWS,
}
# What the sync's revisions are: built by its own callers, never from repository text.
_REVISIONS = (
    "a sha git printed or a ref the job names (`HEAD`, `origin/main`), joined by `..` where it is "
    "a range, or `--cached`: never a string a repository chose"
)
# Each element a launch hands before its options end that the walk cannot read, keyed and held as
# `PASS_THROUGH` is, and the reason it cannot be an option that changes what the launch reaches:
# an option's value, an option the code builds, or an operand its callers have refused when it
# starts with `-`. The launch is then classified by the rest of its argv.
VOUCHED_ELEMENTS: dict[tuple[str, str, str], str] = {
    ("src/stayfixed/attach/doctor.py", "_delivery", "delivered"): (
        "the value of `-e`: `stayfixed-delivery-` and the 32 hex characters of the binding id"
    ),
    ("src/stayfixed/gitenv.py", "fork_points", "base"): (
        "every caller refuses a base that starts with `-` before it asks"
    ),
    ("src/stayfixed/docs/plans.py", "touched_plans.changed", "since"): (
        "a merge base git printed, or the base `touched_plans` refused when it starts with `-`"
    ),
    ("src/stayfixed/docs/plans.py", "written_lines", "since"): (
        "a merge base git printed, or the base `touched_plans` refused when it starts with `-`, "
        "which `lint` runs before it asks for any plan's lines"
    ),
    ("src/stayfixed/ledger/check.py", "_base_ledger", "fork"): "a merge base git printed",
    ("src/stayfixed/assess/base.py", "platform_base", "branch"): (
        "the one operand of `check-ref-format --branch`, which reads no option after `--branch`: "
        "a name shaped like an option is refused as a branch name, never read as an option"
    ),
    ("src/stayfixed/guards/attribute.py", "_extract", "str(archive)"): (
        "the value of `git archive -o` and of `tar -f`, a path under the temporary directory "
        "this run made"
    ),
    ("src/stayfixed/guards/attribute.py", "_extract", "ref"): (
        "`HEAD`, or the merge base git printed"
    ),
    ("src/stayfixed/guards/commit.py", "commits_in", "rev_range"): (
        "refused when it starts with `-`, and closed by the `--` after it"
    ),
    ("src/stayfixed/gitenv.py", "git_path", "name"): (
        "the value of `--git-path`, always one of its callers' constants"
    ),
    ("src/stayfixed/project/detect.py", "_symbolic", "ref"): (
        "`HEAD` or `refs/remotes/origin/HEAD`, its callers' constants"
    ),
    ("src/stayfixed/assess/probes.py", "_commit_types", "f'-n{context.window}'"): (
        "`-n` and the probe's window, an integer"
    ),
    ("src/stayfixed/sync/scan.py", "_committed", "f'HEAD:{name}'"): (
        "`HEAD:` and one of this module's two file names: a revision spec, never an option"
    ),
    ("src/stayfixed/sync/git.py", "guard", "*_MARKER_PATHS"): (
        "the module's own constant: `--git-path` and the name of each in-progress marker"
    ),
    ("src/stayfixed/sync/rules.py", "commit_entries", "rev_range"): _REVISIONS,
    ("src/stayfixed/sync/rules.py", "offending_paths", "*revisions"): _REVISIONS,
    ("src/stayfixed/sync/rules.py", "range_is_memory_only", "base"): _REVISIONS,
    ("src/stayfixed/sync/rules.py", "range_is_memory_only", "tip"): _REVISIONS,
}

# The package function whose environment every git launch is given, `git` with only the variables
# it keeps: an `env=` that calls it overrides nothing worth declaring.
SCRUBBED_ENVIRONMENT = ("src/stayfixed/gitenv.py", "scrubbed_env")
# The sync job's git environment: the owner's own, less git's repository variables, plus the four
# variables `sync.git.job_env` names (no prompt, a non-interactive ssh command the owner's own
# configuration chose, no replace refs, attributes from `HEAD`). The ssh agent has to reach a push,
# which `scrubbed_env` would drop.
_JOB_ENVIRONMENT = (
    "the owner's own environment, less the variables that point git at another repository, plus "
    "`job_env`'s four: the job's git launches are the owner's, signed in as the owner"
)
# Each other `env=` or `executable=` a launch passes, by `(file, function, keyword's source text)`,
# and why it changes nothing the launch's row does not already say. An `executable=` replaces the
# program the argv names, and an `env=` can carry `GIT_CONFIG_COUNT` and its keys and values,
# configuration as strong as `git -c`; either is a finding until it is declared here.
OVERRIDES: dict[tuple[str, str, str], str] = {
    ("src/stayfixed/runner.py", f"_SubprocessRunner.{RUNNER_METHOD}", "env=env"): (
        "the owner's own environment, less the variables that point git at another repository: "
        "the `gh`, `git`, `pre-commit` and plugin launches it runs are the owner's own, signed "
        "in as the owner"
    ),
    ("src/stayfixed/doctor/checks.py", "_wrapper", "env=env"): (
        "the environment doctor was handed, less every `CLAUDE_`, `PLUGIN_` and `STAYFIXED_` "
        "variable, plus the plugin root and project directory the wrapper needs"
    ),
    ("src/stayfixed/sync/git.py", "run", "env=full"): _JOB_ENVIRONMENT,
    ("src/stayfixed/sync/git.py", "git", "env=env"): _JOB_ENVIRONMENT,
    ("src/stayfixed/sync/git.py", "ask", "env=env"): _JOB_ENVIRONMENT,
    ("src/stayfixed/sync/scan.py", "_committed", "env=env"): _JOB_ENVIRONMENT,
    ("src/stayfixed/sync/scan.py", "_scan", "env={**(env or {}), **NO_SIGNATURES}"): (
        "the job's git environment, plus one `git -c`-style entry that keeps signature checks "
        "out of the log gitleaks parses; the scanner's own `GITLEAKS_` variables are dropped"
    ),
    ("src/stayfixed/sync/rules.py", "dirty_memory", "env=env"): _JOB_ENVIRONMENT,
    ("src/stayfixed/sync/rules.py", "commit_entries", "env=env"): _JOB_ENVIRONMENT,
    ("src/stayfixed/sync/rules.py", "offending_paths", "env=env"): _JOB_ENVIRONMENT,
    ("src/stayfixed/sync/rules.py", "range_is_memory_only", "env=env"): _JOB_ENVIRONMENT,
    ("src/stayfixed/prove/run.py", "_launch", "env=dict(env)"): (
        "the caller's own environment, less each variable whose value the runner adapter names "
        "as forging, then the assignments the command itself typed: the test command is the "
        "caller's, and reaches what it reaches"
    ),
}

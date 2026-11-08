"""Which `origin` is the remote a binding was recorded with: one repository, whatever transport.

The remote binds nothing -- the binding is the id in the git common directory -- but a checkout
whose `origin` is not the recorded one hears a note (`origin_note`). The three spellings git and
the forges hand out for one repository -- `git@host:owner/repo`, `ssh://git@host/owner/repo` and
`https://host/owner/repo`, each with or without `.git` -- are one remote, so a clone made over https
of a repository bound over ssh hears nothing, and nothing else is normalised: a different owner,
repository, host, user or port is a different remote, and so is any URL outside those three shapes
unless it is the recorded one byte for byte.
"""

from __future__ import annotations

import itertools

import pytest

from drybag.gitenv import without_userinfo
from drybag.memory.store import NO_REMOTE_SAID, origin_note

# One repository on a host that is not github.com, in every spelling the rule makes one binding.
SPELLINGS = (
    "git@example.com:acme/widget",
    "git@example.com:acme/widget.git",
    "ssh://git@example.com/acme/widget",
    "ssh://git@example.com/acme/widget.git",
    "https://example.com/acme/widget",
    "https://example.com/acme/widget.git",
)


@pytest.mark.parametrize(
    ("recorded", "origin"), list(itertools.permutations(SPELLINGS, 2)), ids=lambda url: url
)
def test_one_repository_is_one_remote_under_every_transport_spelling(
    recorded: str, origin: str
) -> None:
    assert origin_note(recorded, origin) is None


@pytest.mark.parametrize(
    ("recorded", "origin"),
    [
        # The host is a DNS name, which is case-insensitive everywhere.
        pytest.param(
            "git@Example.COM:acme/widget.git", "https://example.com/acme/widget", id="host-case"
        ),
        # A subgroup path, as GitLab hands out, is one path like any other.
        ("git@example.com:acme/tools/widget.git", "https://example.com/acme/tools/widget"),
        # github.com resolves an owner and a repository whatever their case, so there alone the
        # path is compared without it.
        ("git@github.com:Acme/Widget.git", "https://github.com/acme/widget"),
        ("ssh://git@GitHub.com/ACME/widget", "https://github.com/acme/WIDGET.git"),
    ],
)
def test_case_folds_where_the_server_ignores_it(recorded: str, origin: str) -> None:
    assert origin_note(recorded, origin) is None


@pytest.mark.parametrize(
    ("recorded", "origin"),
    [
        # A different owner, a different repository and a different host are other repositories,
        # under the same transport and across two.
        ("git@example.com:acme/widget.git", "https://example.com/fork/widget"),
        ("git@example.com:acme/widget.git", "https://example.com/acme/gadget"),
        ("git@example.com:acme/widget.git", "https://example.org/acme/widget"),
        ("git@example.com:acme/widget.git", "git@example.com:acme/widget-tools.git"),
        ("git@example.com:acme/tools/widget", "https://example.com/acme/widget"),
        # Outside github.com a path's case is the server's to judge, and drybag does not guess.
        pytest.param(
            "git@example.com:acme/widget.git",
            "https://example.com/Acme/Widget",
            id="path-case-off-github",
        ),
        # A host's case folds and a host's spelling does not: neither `www.` nor a trailing dot
        # is the same name to this rule.
        ("git@github.com:acme/widget.git", "https://www.github.com/acme/widget"),
        ("git@github.com:acme/widget.git", "https://github.com./acme/widget"),
        # A user other than `git`, or any userinfo on https, names an account, and none of the
        # three spellings does.
        ("alice@example.com:acme/widget.git", "https://example.com/acme/widget"),
        ("ssh://alice@example.com/acme/widget", "git@example.com:acme/widget"),
        ("https://alice@example.com/acme/widget", "git@example.com:acme/widget"),
        ("git@example.com:acme/widget", "ssh://example.com/acme/widget"),
        # A port is another server as far as this rule knows.
        ("ssh://git@example.com:2222/acme/widget", "git@example.com:acme/widget"),
        ("https://example.com:8443/acme/widget", "https://example.com/acme/widget"),
        # Only https among the web transports, and only one `.git` comes off.
        ("http://example.com/acme/widget", "https://example.com/acme/widget"),
        ("git://example.com/acme/widget", "https://example.com/acme/widget"),
        ("git@example.com:acme/widget.git.git", "https://example.com/acme/widget"),
        # A path is compared as written: no `..` is resolved, no `/` is collapsed, and an absolute
        # scp path or a home-relative one is not the forge's `owner/repo`.
        ("git@example.com:evil/widget", "https://example.com/acme/../evil/widget"),
        ("git@example.com:acme/widget", "https://example.com/acme//widget"),
        ("git@example.com:acme/widget", "https://example.com/acme/widget/"),
        # A segment of dots alone is one a server may resolve rather than read, so a path holding
        # one is not compared across transports even when it is spelled the same in both.
        pytest.param(
            "git@example.com:acme/../widget",
            "https://example.com/acme/../widget",
            id="dot-segments",
        ),
        ("git@example.com:/acme/widget", "https://example.com/acme/widget"),
        ("git@example.com:~acme/widget", "https://example.com/~acme/widget"),
        # Two URLs outside every recognised shape bind only when equal byte for byte.
        pytest.param("/srv/git/widget.git", "/srv/git/gadget.git", id="unread-paths"),
        pytest.param(
            "file:///srv/git/widget.git", "file:///srv/git/gadget.git", id="unread-file-urls"
        ),
    ],
)
def test_a_different_repository_earns_the_note_naming_both(recorded: str, origin: str) -> None:
    # The rule may only ever widen the exact comparison by spellings of one repository, never by
    # two repositories it cannot tell apart.
    # Each named without its userinfo, which may carry a token (`gitenv.without_userinfo`).
    shown = [repr(without_userinfo(url)) for url in (recorded, origin)]
    for said in (origin_note(recorded, origin), origin_note(origin, recorded)):
        assert said is not None and all(name in said for name in shown)


@pytest.mark.parametrize(
    "url",
    [
        pytest.param("/srv/git/widget.git", id="unread-path"),
        "ssh://git@example.com:2222/acme/widget",
        "https://alice@example.com/acme/widget",
        "git@example.com:acme/widget.git",
    ],
)
def test_a_url_is_still_its_own_remote_whatever_its_shape(url: str) -> None:
    # The exact comparison is kept underneath the transport rule: a remote outside the three
    # shapes is the one recorded when it is byte for byte the same.
    assert origin_note(url, url) is None


def test_a_missing_origin_or_a_missing_record_is_said_as_no_remote() -> None:
    assert origin_note(None, None) is None
    gone = origin_note("git@example.com:acme/widget", None)
    added = origin_note(None, "https://example.com/acme/widget")
    assert gone is not None and f"`origin` is {NO_REMOTE_SAID}," in gone
    assert added is not None and f"recorded with {NO_REMOTE_SAID};" in added

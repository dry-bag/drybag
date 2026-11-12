"""Reject AI/tool attribution trailers in commit messages.

The rule this enforces is a developer policy, not a project convention, so it is deliberately
*not* restated here: this module owns the mechanism, not the norm.

A check rather than a note: the agent harness places an instruction to append a trailer in the
system prompt, beside the git command being run, so a rule delivered as context competes with it
on every commit. A check runs after the message exists and is part of no prompt.

Two surfaces share one pattern set, so they cannot drift apart:

* ``commit check --range A..B`` — CI, on every push and every pull request. It sees every
  commit; a pull request's own ``drybag.toml`` can switch it off
  (``commit_messages.attribution_check``).
* ``commit strip FILE`` — what the ``prepare-commit-msg`` hook in ``githooks`` runs. Local and
  early, so the trailer is gone before the commit exists. ``git commit --no-verify``
  skips ``pre-commit`` and ``commit-msg`` but *not* ``prepare-commit-msg``, so this survives
  the usual bypass.

Adding a vendor means **all three** tables: its word in ``_VENDORS``, which the footer and marker
rules read; its mail domain in ``_VENDOR_DOMAINS``; and its product name in ``_PRODUCTS``. Neither
trailer table subsumes the other: a vendor whose domain does not spell its product (Windsurf sends
from codeium.com) needs the domain, and one with no domain of its own lands **only** in
``_PRODUCTS``.

**Only the trailing attribution block is judged.** Trailers and footers are appended at the end,
and the body above is prose that may name providers, model ids and quoted trailers: judging it
would let ``strip`` delete a body sentence, and nothing puts one back. The block is the last
paragraph, plus each paragraph above it whose every line is an attribution line, because the
canonical harness attribution is two paragraphs, a footer and then a trailer. The walk cannot
step *over* a paragraph: one non-matching line ends it. So a message that quotes forbidden
trailers as examples, in paragraphs of nothing else, loses them to ``strip`` and fails
``check``; describe the trailer instead, or keep a sentence of your own in the same paragraph.

The trailer rule reads the trailer's *value*: an address at a vendor's mail domain, or a whole
name that is a product phrase. A value that continues into a WORD past its last ``>`` is a
sentence; punctuation there is not. A footer, too, must end where its product name ends
(``_FOOTER_WORD``).

**The domain rule's cost is chosen, not overlooked** — a person whose employer is a vendor
(``alice@openai.com``) is indistinguishable from that vendor's bot by address alone, and is
flagged. Dropping the domain rule to spare them would miss every bot whose trailer name is not
a product phrase, which is most of them.

Scope and limits. Only whole lines that *are* an attribution trailer or footer are matched, so a
violation phrased in prose is not caught. Only commit messages are judged, never file content;
pull-request bodies, review comments and branch names remain on judgement. Both functions split
with ``str.splitlines()`` and rejoin with LF, so a stripped CRLF message comes back normalised,
and a trailer folded onto a continuation line is matched on its first line only.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from drybag.errors import Refusal
from drybag.gitenv import NO_ANSWER, answer_bytes, git_run

if TYPE_CHECKING:
    from drybag.config.schema import Config

# Vendor tokens are only ever used inside an anchored construct below, never on their own: a
# repository legitimately contains `claude_cli`, `claude-opus-5`, and prose about the
# subscription-backed provider, none of which may trip the check.
_VENDORS = (
    r"claude|anthropic|codex|openai|chatgpt|copilot|cursor|gemini|devin"
    r"|windsurf|codeium|mistral|aider"
)

# A `-by:` trailer: any `<Something>-by:` key, because agent harnesses use Reviewed-by,
# Signed-off-by and Tested-by alike; the value decides (`_trailer_offence`). Only the key is a
# pattern: `_trailer_value` trims the rest, since a lazy value ended by blanks is quadratic.
_TRAILER = re.compile(r"[ \t]*[\w-]*-by:", re.IGNORECASE)
# The address rule: the bot's own domain. A person employed there is the documented cost.
# `github.com` (human web-UI commits) and `google.com` (every Google employee) are absent, since
# listing either fails honest commits wholesale; their products are caught by name in `_PRODUCTS`.
# Gemini has no domain here and only two product phrases, a known gap on this surface.
#
# A vendor's domain or any subdomain of it, `@(?:[\w-]+\.)*<domain>\b`, read a label at a time by
# `_names_a_vendor_domain`: a repeat of labels in `re` keeps a record for every label.
_VENDOR_DOMAINS = re.compile(
    r"(?:anthropic\.com|openai\.com|cursor\.(?:sh|com)|codeium\.com"
    r"|windsurf\.com|mistral\.ai|devin\.ai|aider\.chat)\b",
    re.IGNORECASE,
)
# What follows an `@`: the labels and the dots between them, read once.
_DOMAIN_RUN = re.compile(r"@([\w.-]*+)")
# The name rule: `fullmatch`, so the display name is a product phrase AND NOTHING ELSE, since
# `Claude Lemaire`, `Devin Clark` and `Gemini Rossi` are people. `Devin AI`, `Codex CLI` and
# `Claude Code Bot` are not matched: a bot named neither exactly nor from a vendor domain is a gap.
#
# A model's version words are possessive, which changes no verdict under `fullmatch`. A word's
# first character is read ahead of its possessive rest, so a pass can fail only before it reads a
# run: the shape every supported Python reads alike (CONTRIBUTING.md, "Tests").
_PRODUCTS = re.compile(
    r"(?:claude code|claude (?:opus|sonnet|haiku)(?: [\w.][\w.]*+)*+|github copilot|copilot"
    r"|cursor agent|cursor|openai codex|codex|chatgpt|devin|windsurf|aider|gemini cli"
    r"|gemini code assist)",
    re.IGNORECASE,
)
# What ends a footer: past the vendor word the line must be *finished*, not carry on into a
# sentence (`Generated with Claude Code and then reviewed by a human.` is prose). What may follow:
#
# * more of the product's name (`Code`, `Opus 5`, `CLI`): a proper noun, so a word beginning with
#   a capital or a digit; a word beginning lowercase is prose. `(?-i:...)` because the pattern is
#   case-insensitive.
# * a version or a link (`v1.2`, `(https://claude.com/claude-code)`): a token with a digit or `/`.
# * the canonical footer's markdown link target, then any run of non-word characters.
#
# The cost: a footer typed in lowercase, or ending in an ordinary word, is missed here, while its
# paired `Co-Authored-By:` trailer is still caught; widening this deletes body sentences.
#
# Each word is read once, whole, and never given back, so a line of many words is linear. And
# `_is_footer` reads the words one match at a time, then the end, rather than as a possessive
# repeat of a group, which Python 3.11.0 to 3.11.4 end where a failed pass stopped
# (CONTRIBUTING.md, "Tests").
_FOOTER_WORD = re.compile(r"[ \t]+(?:\S*[\d/]\S*|(?-i:[A-Z0-9])[\w.]*)", re.IGNORECASE)
_FOOTER_END = re.compile(r"(?:\]\([^)\s]*\))?\]?[^\w]*$")
# A footer names the vendor as a word, never as a prefix of a package (`openai-python`) or a
# possessive (`openai's`).
_FOOTER = re.compile(
    rf"^[ \t]*(?:\U0001F916[ \t]*)?generated (?:with|by)[ \t]*\[?(?:{_VENDORS})\b(?![-'])",
    re.IGNORECASE,
)
# The marker is the whole line, optionally `by <tool>`; a sentence that starts with the words
# and goes on (`AI-generated summaries are now cached`) is prose.
_MARKER = re.compile(
    r"^[ \t]*(?:\U0001F916[ \t]*)?ai[- ]generated(?:[ \t]+(?:by|with)[ \t]+\S.*)?[ \t]*$",
    re.IGNORECASE,
)
# What tells a trailer's trailing punctuation from a sentence continuing past the address: one
# word character, `\w` and not `[A-Za-z]`, since a tail is prose in any script.
_WORD = re.compile(r"\w")


def _trailer_value(line: str) -> str | None:
    """The value of the `-by:` trailer `line` is, or `None` where it is not one: the rest of the
    line past the key, without the blanks around it. `line` holds no line break, since both
    readers cut the message with `str.splitlines()`. A value of blanks alone names nobody."""
    key = _TRAILER.match(line)
    if key is None:
        return None
    return line[key.end() :].strip(" \t") or None


def _trailer_offence(line: str) -> bool:
    value = _trailer_value(line)
    if value is None:
        return False
    name, bracket, address = value.partition("<")
    # A value of one word is a BARE ADDRESS (`Co-Authored-By: noreply@anthropic.com`); a value
    # with a space is a display name or a sentence.
    if not bracket and len(name.split()) == 1:
        address = name
    # A value that CONTINUES INTO A WORD past its address is a sentence
    # (`Reviewed-by: Copilot <x@y.z> said nothing useful.`). A word character, not any character:
    # `<noreply@anthropic.com>.` with a typed full stop is still a trailer, and so is one whose
    # `>` was knocked off. After the LAST `>`, since a display name may carry brackets of its own
    # (`Claude <bot> <noreply@anthropic.com>`). Prose ending in `>` is flagged, the cheap error.
    _, bracket, tail = address.rpartition(">")
    if bracket and _WORD.search(tail):
        return False
    if _names_a_vendor_domain(address):
        return True
    return _PRODUCTS.fullmatch(name.strip()) is not None


def _is_footer(line: str) -> bool:
    """Whether `line` is a generated-with footer: its words up to the vendor's (`_FOOTER`), then
    each word past it that is more of the product's name, a version or a link (`_FOOTER_WORD`),
    and then nothing but the line's end (`_FOOTER_END`)."""
    footer = _FOOTER.match(line)
    if footer is None:
        return False
    end = footer.end()
    while (word := _FOOTER_WORD.match(line, end)) is not None:
        end = word.end()
    return _FOOTER_END.match(line, end) is not None


def _names_a_vendor_domain(address: str) -> bool:
    """Whether an `@` in `address` is followed by a vendor's domain, or by labels and then one.

    Each run after an `@` is read once: a vendor is tried at its start and after each dot that
    closes a label, up to the first label that is empty, which is where the pattern's labels end;
    and no run of labels after an `@` holds another `@`."""
    for run in _DOMAIN_RUN.finditer(address):
        labels = run.group(1)
        start = 0
        while True:
            if _VENDOR_DOMAINS.match(labels, start):
                return True
            dot = labels.find(".", start)
            if dot <= start:
                break
            start = dot + 1
    return False


_PATTERNS: tuple[tuple[str, Callable[[str], bool]], ...] = (
    ("attribution trailer naming an AI tool", _trailer_offence),
    ("generated-with footer", _is_footer),
    ("AI-generated marker line", lambda line: _MARKER.search(line) is not None),
)


class Offence(NamedTuple):
    line: int
    label: str


class Commit(NamedTuple):
    sha: str
    message: str


class Violation(NamedTuple):
    sha: str
    offences: tuple[Offence, ...]


class Report(NamedTuple):
    commits: int
    violations: tuple[Violation, ...]


# A wall-clock bound on one `git log` over a range: a named cap (CONTRIBUTING.md#named-caps), and no
# shipped file changes with it. Larger than `gitenv.GIT_TIMEOUT_SECONDS` because a pull-request
# range can be hundreds of commits; a `git log` that takes longer than this is a repository this
# command cannot judge in CI.
LOG_TIMEOUT_SECONDS = 60
ATTRIBUTION_LABELS = tuple(label for label, _ in _PATTERNS)


def _final_paragraph_start(lines: list[str], end: int | None = None) -> int:
    """Index of the first line of the last paragraph of `lines[:end]`, blanks included in it.

    The scan starts at the last **non-blank** line: a trailing blank or whitespace-only line would
    otherwise make an empty final paragraph, and one trailing space would disable the check.
    `end` lets `_attribution_block_start` ask the same of the text above a judged paragraph.
    """
    end = len(lines) if end is None else end
    while end > 0 and not lines[end - 1].strip():
        end -= 1
    for index in range(end - 1, -1, -1):
        if not lines[index].strip():
            return index + 1
    return 0


def _is_attribution(line: str) -> bool:
    return any(matches(line) for _, matches in _PATTERNS)


def _paragraph_is_all_attribution(lines: list[str], start: int, end: int) -> bool:
    """True when `lines[start:end]` has content and every non-blank line of it is attribution.

    Blank lines do not vote, and an all-blank slice is *not* all attribution, or the walk would
    step through it into the body.
    """
    content = [line for line in lines[start:end] if line.strip()]
    return bool(content) and all(_is_attribution(line) for line in content)


def _attribution_block_start(lines: list[str]) -> int:
    """Index of the first line judged: the last paragraph, plus wholly-attribution ones above.

    The walk goes up **only while the paragraph it reaches is attribution to the last line**, so
    the first body line ends it and `strip_message` never reaches a sentence above it.
    """
    start = _final_paragraph_start(lines)
    if not _paragraph_is_all_attribution(lines, start, len(lines)):
        return start
    while start > 0:
        earlier = _final_paragraph_start(lines, start)
        if not _paragraph_is_all_attribution(lines, earlier, start):
            break
        start = earlier
    return start


def offending_lines(message: str) -> list[Offence]:
    """`(line number, label)` for every attribution line in `message`'s attribution block.

    The offending text itself is never carried: a commit message is repository-authored, and
    only what this module computed travels to a summary or a hook's context.
    """
    lines = message.splitlines()
    start = _attribution_block_start(lines)
    hits: list[Offence] = []
    for number, line in enumerate(lines[start:], start=start + 1):
        for label, matches in _PATTERNS:
            if matches(line):
                hits.append(Offence(number, label))
                break
    return hits


def strip_message(message: str) -> str:
    """Drop the attribution block's attribution lines and the blank their removal orphans.

    **The body is never rewritten.** Only lines at or after the block's start are removed, plus
    the blank separator the removal leaves dangling at the end; a doubled blank inside the body
    stays doubled. A message with no offence is returned byte for byte.
    """
    lines = message.splitlines()
    doomed = {offence.line - 1 for offence in offending_lines(message)}
    if not doomed:
        return message
    start = _attribution_block_start(lines)
    kept = lines[:start] + [
        line for index, line in enumerate(lines[start:], start=start) if index not in doomed
    ]
    while kept and not kept[-1].strip():
        kept.pop()
    return "\n".join(kept) + "\n" if kept else ""


def commits_in(root: Path, rev_range: str) -> list[Commit]:
    """`(sha, message)` for each commit in `rev_range`, oldest first.

    **NUL is the only delimiter.** `%x00` separates a sha from its message and `-z` ends each
    record with NUL, so the stream alternates the two. NUL is the one byte a commit message cannot
    carry; any other byte in a body could split a commit into two records and hide its trailer.

    The range is refused when it is shaped like an option (principle 5) and closed with `--` so it
    can never be read as a pathspec.
    """
    if rev_range.startswith("-"):
        raise Refusal(f"{rev_range!r} looks like an option, not a revision range")
    code, out = git_run(
        root,
        "log",
        # Judged as UTF-8, while git prints in whatever `i18n.logOutputEncoding` says.
        "--encoding=UTF-8",
        "--reverse",
        "-z",
        "--format=%H%x00%B",
        rev_range,
        "--",
        timeout=LOG_TIMEOUT_SECONDS,
    )
    # No refusal below carries `git log`'s stderr, which is repository-authored and unbounded;
    # the range is the caller's own string, and the only thing printed.
    if code == -1:
        raise Refusal(f"{NO_ANSWER}, so {rev_range!r} was not read")
    if code != 0:
        raise Refusal(f"git could not read {rev_range!r}; run it yourself to see why")
    # A commit whose `encoding` header git cannot convert from arrives raw, and a pull request
    # can push one: undecodable, it cannot be judged.
    try:
        text = answer_bytes(out).decode("utf-8")
    except UnicodeDecodeError:
        raise Refusal(
            f"git printed a message in {rev_range!r} that is not UTF-8 text, so it cannot be judged"
        ) from None
    # Positional: sha, message, sha, message, and `-z` leaves one empty field at the end. A
    # dangling field, which cannot happen, would be a sha with no message and is dropped.
    fields = text.split("\x00")
    if fields and not fields[-1]:
        fields.pop()
    return [Commit(fields[index], fields[index + 1]) for index in range(0, len(fields) - 1, 2)]


def check_range(root: Path, rev_range: str, config: Config) -> Report:
    """Judge every message in `rev_range`, unless `attribution_check` switches the rules off.

    The log runs either way: with the flag false the report still counts the messages, and an
    unreadable range is still a refusal.
    """
    commits = commits_in(root, rev_range)
    violations: list[Violation] = []
    if not config.commit_messages.attribution_check:
        return Report(len(commits), ())
    for sha, message in commits:
        offences = offending_lines(message)
        if offences:
            violations.append(Violation(sha, tuple(offences)))
    return Report(len(commits), tuple(violations))


def harness_says_what_commits_carry(home: Path | None) -> bool:
    """Whether the machine owner's Claude Code settings set `attribution.commit`, the harness's own
    word on what a commit it makes carries, to text.

    `commit strip` gives way to it: the trailer is then the person's choice. Set empty or to
    whitespace, it says commits carry nothing, and the strip goes on. Only the owner's settings
    file under `home` is read, never one a repository commits, because a clone could otherwise
    turn the hook off. It is read as a regular file only (`fsops.read_regular_text`), since a FIFO
    there would hold every commit; a file that is missing, unreadable or not one JSON object sets
    nothing. All or nothing: with text there, every attribution line the strip would take is kept.
    """
    from drybag import fsops
    from drybag.errors import Failure
    from drybag.harnesses import CLAUDE, lenient_settings
    from drybag.jsonobject import json_object

    if home is None:
        return False
    (settings,) = CLAUDE.settings
    try:
        text = fsops.read_regular_text(home / settings)
        document = json_object(lenient_settings(text), settings, error=Failure)
    except (OSError, UnicodeDecodeError, Failure):
        return False
    attribution = document.get("attribution")
    commit = attribution.get("commit") if isinstance(attribution, dict) else None
    return isinstance(commit, str) and commit.strip() != ""

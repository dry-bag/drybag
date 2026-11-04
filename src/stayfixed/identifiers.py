"""One definition of what a ledger identifier looks like, from its register's prefix.

A prefix is the kind of string that gets respelled at each point of use — a regular expression
in one reader, a format string in a writer, a filename glob in a third — until a dozen copies
disagree about what an identifier is and no one of them can be corrected alone. One object that
every reader and writer asks is what makes a prefix that changes change all of them together,
and it is why this grammar exists at all rather than as a constant per module. A leaf module:
the ledger builds each register's identifiers from it, and the plan lint (`Fixes BR-nnn`) reads
the bug ledger's through its register, from `stayfixed.ledger.api`. The prefix is
repository-controlled (principle 5): it is interpolated into patterns and filenames, so it is
held to a shape before either happens.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cached_property

from stayfixed.errors import Refusal

# Upper-case letters and digits, one to eight characters, letter first. Not a budget but a named cap
# (CONTRIBUTING.md#named-caps) on what may be interpolated into a regular expression and a filename,
# and the eight is what a `PREFIX-nnn.md` filename stays readable at.
PREFIX = re.compile(r"\A[A-Z][A-Z0-9]{0,7}\Z")
# Three digits or more: `renumber` and every reader enforce it. The plan lint's `Fixes` rule
# and the allocator's `git log` reader build their patterns from this same constant, so none of
# them can disagree about the minimum. Public for that reason: a reader that respells the rule
# inline is a spelling `mutations/`'s "the identifier digit rule widens and the allocator keeps
# the old one" cannot reach, and a widened rule would leave it counting by the old one.
DIGITS = r"\d{3,}"


@dataclass(frozen=True)
class Identifiers:
    prefix: str

    def __post_init__(self) -> None:
        if not PREFIX.match(self.prefix):
            raise Refusal(
                f"[ledger] id_prefix {self.prefix!r} must match {PREFIX.pattern}; "
                "it is interpolated into patterns and filenames"
            )

    @cached_property
    def exact(self) -> re.Pattern[str]:
        return re.compile(rf"\A{re.escape(self.prefix)}-({DIGITS})\Z")

    @cached_property
    def mention(self) -> re.Pattern[str]:
        return re.compile(rf"\b{re.escape(self.prefix)}-{DIGITS}\b")

    @cached_property
    def fixes(self) -> re.Pattern[str]:
        """The claim a plan makes that obliges it to carry a `Premise:` line."""
        return re.compile(rf"\bFixes\s+{re.escape(self.prefix)}-{DIGITS}\b")

    def is_identifier(self, text: str) -> bool:
        return self.exact.match(text) is not None

    def number(self, identifier: str) -> int:
        match = self.exact.match(identifier)
        if match is None:
            raise Refusal(f"{identifier!r} is not a {self.shape} identifier")
        return int(match.group(1))

    def format(self, number: int) -> str:
        return f"{self.prefix}-{number:03d}"

    @property
    def shape(self) -> str:
        """How a message spells the contract: `BR-nnn`."""
        return f"{self.prefix}-nnn"

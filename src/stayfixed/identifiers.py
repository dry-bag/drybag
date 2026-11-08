"""What a plan's claim to fix a bug looks like: `Fixes BR-nnn`.

A leaf module, read by the plan lint: a plan that makes this claim owes a `Premise:` line. The
prefix is fixed at `BR`, because no project has a configured one to read any more.
"""

from __future__ import annotations

import re

# Three digits or more: fewer is a different shape, which counts a heading or a number that was
# never an identifier.
BUG_FIXES = re.compile(r"\bFixes\s+BR-\d{3,}\b")

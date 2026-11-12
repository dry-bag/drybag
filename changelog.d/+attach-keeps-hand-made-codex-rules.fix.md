`drybag attach` no longer writes over a `.codex/rules/` file it did not write: a file at a rule's
name that does not hold the bytes attach's ledger records, yours even when it holds the overlay's
very bytes, is left as it is, unrecorded and out of the exclude block, and named as `Codex rule
file left`; `drybag detach` leaves it too. A re-attach now takes back a copy the overlay dropped
while it is untracked and as attach wrote it, as `detach` does, instead of leaving it to apply as a
standing instruction. `attach --check` names both, one line each.

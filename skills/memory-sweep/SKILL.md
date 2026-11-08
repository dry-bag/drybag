---
name: memory-sweep
description: Sweep the working-memory store — inventory by size, verify anchors resolve, rewrite notes to rule-plus-pointer. Use when memory notes have accumulated history or the index has grown.
---

# Sweeping the memory store

1. **Inventory.** Run `stayfixed memory inventory --json`: every note with its word count,
   type, provenance and staleness. Sort by words, descending; the tail above ~400 words is
   where the value is.
2. **Verify anchors before cutting.** For each note, open the ledger entry behind every
   identifier it names and confirm the pull requests it cites are merged. This is the sweep's
   own job and nothing does it for you. A pointer to nothing is worse than the retelling it replaced.
3. **Rewrite to rule plus pointer.** Keep the rule, one line of why, how to apply, and a bare
   identifier for the evidence. History belongs to the ledger, the roadmap or the retro.
4. **Merge on close coupling.** Two notes firing on the same trigger, or each needing the
   other to be usable, are one note. A fact mechanized elsewhere is deleted, not kept.
5. **Regenerate the index.** Run `stayfixed memory index`, then `stayfixed memory index --check`.
6. **Hand the rewrites back for review.** A rewritten note is unreviewed again, and so no longer a
   standing rule: tell the owner which notes changed, and leave `stayfixed memory promote --changed`
   to them once they have read the diff.

Conventions for what a note is and how the index routes: [references/protocol.md](references/protocol.md).

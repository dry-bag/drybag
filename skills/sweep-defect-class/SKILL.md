---
name: sweep-defect-class
description: Turn one defect into its class and close every instance — enumerate the shape across the tree, prove which tests take the branch, fix or file each hit, and declare the mutation that reddens each fix. Use after a bug fix whose shape could recur.
---

# Sweeping a defect class

1. Name the shape, not the incident. State the defect as a predicate over source — a search
   pattern, or a rule about the syntax tree — that matches the instance you found and would
   match another. "An assertion satisfied by several code paths" is a shape; "the doctor
   test passed with its gate torn out" is an instance.
2. Enumerate. Run the predicate over the whole tree and list every hit with its file and
   line. Assert the list is non-empty before doing anything with it: a search that found
   nothing may be a search that ran over nothing.
3. Prove which tests take the branch. For each hit, tear the guard out — delete the
   check, invert the condition, return the surviving arm's value — and run the suite. A
   test that stays green with the guard gone is asserting something else; write down which
   tests reddened, and for which reason. A mutation that reddens for an accidental reason
   (a deleted name, a status a surviving arm also produces) is worse than none, because it
   reads as coverage.
4. Fix every instance or file it. A hit outside the change's scope becomes a ledger entry
   (the `file-bug` skill), with the predicate quoted so the next sweep finds it again;
   `stayfixed bugs check` says whether the ledger still agrees with the tree.
5. Declare the mutation for each fix: the one line to change, and the test that must go red
   when it does. Run the declared set unfiltered — a filtered run cannot see an entry an
   earlier change declared and this one invalidated — and read its last line.
6. Record the class where the next reader meets it: a sentence in the test's comment naming
   the shape and the instance, and one in the commit. The ten shapes an assertion turns out
   vacuous in are the reference: [references/vacuous-oracles.md](references/vacuous-oracles.md).

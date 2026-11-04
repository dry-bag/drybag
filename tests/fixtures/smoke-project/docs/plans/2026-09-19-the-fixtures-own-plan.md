# The fixture's own plan

**Scope:** this document, and nothing else. It exists so that `stayfixed plan check` has a
plan to lint in this project, and so that the four
rules that command holds a plan to are exercised by a document that satisfies them.

## Context

`plan check` lints the plans a range touches. A project whose plans directory held only a
README would give the gate nothing to read, and a gate that reads nothing reports success
for its whole life. This file is what it reads.

## Steps

- [ ] **Step 1: Read the fixture**

Read `AGENTS.md` and `docs/roadmap.md`. Both are in this project and both resolve, which is
the first rule: a backticked path in a plan names something that exists.

- [ ] **Step 2: Write the step down before running it**

Run the gate and record what it answered. The phrasing matters: a step that announces its
own outcome is the second rule's finding, so this one says what to run and leaves the answer
to the run.

- [ ] **Step 3: Note where a new document would go**

A document this plan would add lives at `docs/specs/a-future-spec.md` (create), which does
not exist yet and says so on its own line.

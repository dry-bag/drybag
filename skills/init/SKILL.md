---
name: init
description: Take a repository onto stayfixed — show what it detected, ask the questions a person may answer, and write stayfixed.toml with the roadmap, trail and bug-ledger files the checks read. Use when a project has no .stayfixed/manifest.json yet, or the user asks to initialise stayfixed in it.
---

# Initialising a project

Ask through the harness's ask-the-user tool when it has one, and one plain question per turn
when it does not; [references/asking.md](references/asking.md) fits each step to the
harness's limits. Never run this skill in a forked context: a subagent cannot ask.

## Walk

1. Run `stayfixed init --questions --json`. It refuses a repository that already has
   `.stayfixed/manifest.json` or a `stayfixed.toml` (see the first rule). Otherwise `questions.properties` holds eight questions, asked in the order
   `questions.required` lists them, each with its `default` (what `stayfixed init --yes` alone
   would write), its `x-stayfixed-source`, its `x-stayfixed-flag` and its
   `x-stayfixed-tradeoff`: four lines, what the answer gives (`get`), what it gives up
   (`give_up`), what it leaves behind (`trace`) and how to undo it.
2. Offer the skip first: show every default in one list and ask whether to take them all. On a
   yes, go to step 5 with no answer flag. A name with no default is "not derivable": ask for it
   even then.
3. Show the name and the base branch, each with its source, as **one** confirm question. On a
   "no", ask which is wrong, then ask only that.
4. Ask each remaining question in order, one at a time: its options, the default marked, and its
   four lines as written. If the user picks the overlay and its option says the setup skill
   creates one next, ask one follow-up: set one up now, or keep notes on this machine until
   then, which is the answer `local-only`.
5. Build the command: `--yes --dry-run`, then each answer that differs from its default as its
   `x-stayfixed-flag`, once per item for a list, such as
   `stayfixed init --yes --dry-run --name widget --memory-mode in-repo`. Leave the plugins out:
   they are not `init`'s. Run it and relay both reports, the `picked:` list
   and every `note:` line. Ask for a final yes. **Silence, a timeout or an empty answer is a
   no.**
6. On a yes, run the same command without `--dry-run`, and relay the real run the same way.
7. If plugins were chosen, run the plugins question's `x-stayfixed-flag` with each one. It is a
   whole machine setup, not only an install, as the question's `trace` says: relay that first.
8. If the answer was the overlay: when the machine records none, hand over to the `setup`
   skill to create or record one; then hand over to the `attach` skill to bind this
   repository. Each asks its own confirmations. Come back here afterwards.

## Rules

- **A `stayfixed.toml` the user wrote answers the questions.** Skip steps 2–4 and 7 and run
  steps 5 and 6 with no answer flag: the dry run, the relay, the explicit final yes, then the write. The
  file is kept; a missing `[stayfixed] version` is the one thing added, and a `note:` line says so.
- **A `failed:` line from `init` over a `stayfixed.toml` the user wrote means the next command
  could not load that file.** Nothing was written. Relay the sentence, fix the file with the
  user, and run again.
- **A repository with `.stayfixed/manifest.json` is refused.** `init` writes a scaffold once.
  Never delete the manifest to get past it.
- **Nothing is written when anything is refused.** Relay every `REFUSED` line, fix the cause
  with the user, and run again.
- **Never hand-edit `.stayfixed/manifest.json`.** It is the tool's.

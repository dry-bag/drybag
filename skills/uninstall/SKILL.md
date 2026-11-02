---
name: uninstall
description: Remove stayfixed's scaffold from a repository, leaving hand-edited files in place and listed. Use when the user asks to uninstall or remove stayfixed from a project.
---

# Uninstalling

`stayfixed uninstall` removes every file stayfixed wrote whose bytes are still the ones it wrote,
takes its sections out of files that hold other text, and removes its ledger. A file the user
edited stays where it is and is listed.

1. An attached repository needs no step of its own: `uninstall` runs `detach` first, and a
   `note:` line says so, which the dry run says it would. Relay it: the overlay's plugin and the
   allow rules `attach` placed go with it.
2. Run `stayfixed uninstall --dry-run` and relay both reports and every `note:` line. The note
   about `AGENTS.md` means the real run judges the skeleton after taking stayfixed's section
   out, so a file the dry run calls edited there may still go.
3. A `note:` counting files under `.stayfixed/local/` means the real run will refuse. They are
   the user's notes kept out of git, or a file kept out of git that changed since stayfixed wrote
   it, and the ignore block this command removes is what keeps them out of it. Relay the count.
   A file the report lists `skip_modified` there is step 4's question; moving the rest is the
   user's decision. Never move or delete them yourself.
4. For each file left in place, ask the user. Add `--force <path>` only for a file they name,
   with the path exactly as the report prints it. Forcing `AGENTS.md` takes stayfixed's section
   out of it, never the rest of the file.
5. If any `--force` was added, run `stayfixed uninstall --dry-run` again with the same flags and
   relay the new reports before anything is removed.
6. Run `stayfixed uninstall` with the same flags, and relay both reports and the count of files
   left in place.
7. Tell the user what stays on the machine: any approval in the trust record, which no command
   withdraws (an edited note is unreviewed again, its digest having changed), and the deny rules
   `setup` merged into the user settings file, which are the machine's and stay.

## Rules

- **An exit of 1 from a plan removed nothing.** A `REFUSED` section names each artifact and why.
  Relay it and stop. An exit of 1 from the `detach` it runs first on an attached repository may
  come after part of what `attach` placed was withdrawn: relay its sentence, and once its cause is
  dealt with run `stayfixed uninstall` again, which finishes while the render is still there. Once
  that `detach`, or an `attach` cut short, has left the ledger without the render, `uninstall`
  refuses counting the ledger among the files under `.stayfixed/local/`: run `stayfixed detach`,
  which finishes from the ledger, then `stayfixed uninstall`.
- **An exit of 2 is a refusal, and it may have come part-way through.** Files kept under
  `.stayfixed/local/` counted before the run, and a `--force` path outside the root come before
  anything is removed. A refusal from the `detach` it runs comes before its own first removal.
  A file that cannot be removed, or files still under `.stayfixed/local/` after the write-once
  pass, stop the run part-way: what was removed stays removed, and `stayfixed.toml` and the
  manifest stay so the next run can finish. Relay it as printed, run `git status` to show the
  user what changed, and after they deal with the cause run `stayfixed uninstall --dry-run`
  again.
- **A refusal saying git ignores files at a place a `[paths]` value chose removed nothing.**
  Relay it with the files it names. Taking stayfixed's part out of them by hand, or taking that
  key out of `stayfixed.toml` so the run leaves them in place and lists them, is the user's
  decision; never do either yourself.
- **A target printed as `<id>` is one the manifest recorded outside the path grammar.** Relay it
  as printed, and never look up or guess the path behind it.

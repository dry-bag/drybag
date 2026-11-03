---
name: upgrade
description: Upgrade the stayfixed scaffold in a repository after a plugin update, keeping every hand edit. Use when the user asks to upgrade, update or refresh stayfixed's files, or after the plugin version changed.
---

# Upgrading the scaffold

`stayfixed upgrade` moves `[stayfixed] version` to the stayfixed running and refreshes every
scaffold file whose bytes are still the ones stayfixed wrote. A file the user edited is skipped
and named, never overwritten.

1. Run `stayfixed upgrade --dry-run` and relay what it prints: the opening line, the
   `stayfixed.toml:` line with each key it would move, the `scaffold:` report with each file's
   verdict, and every `note:` line.
2. For each file reported `skip_modified`, edited by the user or never written by stayfixed, ask
   whether the user wants it overwritten. Only on a yes for that file, add `--force <path>` for
   it, with the path exactly as the report prints it. Never force a path the user did not name.
3. If any `--force` was added, run `stayfixed upgrade --dry-run` again with the same flags and
   relay the new report, so the user sees what forcing changes before anything is written.
4. Run `stayfixed upgrade` with the same flags, and relay the real run's report the same way.
5. Ask the user to commit `stayfixed.toml`, `.stayfixed/manifest.json` and the changed files
   together.

## Rules

- **An exit of 1 wrote nothing.** A `REFUSED` section names each artifact and why. Relay every
  line and stop.
- **An exit of 2 is a refusal, and it may have come part-way through.** A refusal about the
  project itself — not initialised, no `stayfixed.toml`, a newer, unreadable or unordered
  recorded version, a key written in a shape it will not edit — comes before any write. One that
  says a file cannot be written comes while writing: what was done before it is on disk and recorded.
  Relay it as printed, run `git status` to show the user what changed, and after they fix the
  cause run `stayfixed upgrade --dry-run` again, which plans from what is there now. When it
  says the project records a newer stayfixed than the one running, the plugin is what needs
  updating: relay that, and never edit `[stayfixed] version` to get past it.
- **`stayfixed.toml` keeps every byte but the values it moves.** If the command refuses to
  rewrite a key because of how the file writes it, relay the refusal: it names the key and the
  value to set by hand.
- **A `note:` about records this stayfixed does not produce is not an error.** Those files were
  left where they are, on purpose.
- **A file kept out of git is refreshed only while it holds what stayfixed last wrote there.**
  One that changed since is skipped like an edited file, because nothing brings it back once it
  is overwritten. A copy left behind where the artifact no longer goes (its id left
  `[artifacts] local`, or its `[paths]` value moved) is removed as `relocated` while it holds
  those bytes, and skipped once it changed. Ask before forcing a skipped one, like any other.
- **A refusal saying git ignores files at a place a `[paths]` value chose wrote nothing.** Relay
  it with the files it names. Pointing that key at a path git does not ignore, or taking it out,
  is the user's decision; never edit `stayfixed.toml` or an ignore file to get past it.
- **A target printed as `<id>` is one the manifest recorded outside the path grammar.** Relay it
  as printed, and never look up or guess the path behind it.
- **There are no hooks to re-trust.** `init` writes no project-level hook entries, so an upgrade
  changes none.

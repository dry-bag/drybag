# Methodology

drybag is the tooling half of a way of working with coding agents. This directory is the
other half: the principles the tooling exists to hold, each stated once, each with the
sources that back it and a plain statement of how well they do.

Two files:

- [principles.md](principles.md) — nine numbered principles. Each one has a statement, what
  drybag does about it today, its sources, and a **Backing** line.
- [sources.md](sources.md) — the citation pack. Every `[S<n>]` in the principles resolves to
  a row here; every row is cited at least once. A test holds both directions.

## How to read a Backing line

A principle says one of three things about its evidence, and the word is chosen by the
weakest link in the chain behind the claim the label is about, not the strongest. Where a
principle's mechanism is sourced and a comparative claim built on top of it is not, the
label follows the mechanism — that is the claim it is about — and the prose says in as many
words what the sources do not reach:

- **sourced** — a dated primary source outside this project states the claim, or states the
  platform fact the claim rests on. The sources are listed and the principle says what each
  one establishes.
- **measured** — the claim rests on a measurement this project made and recorded with its
  date: a count, a byte size, a probe's exit code. Measurements go stale; the date is part
  of the claim.
- **thin** — the principle is a working rule that has earned its place in practice and has
  no independent backing beyond that. It is stated as a rule because the alternative is to
  hide it inside the tooling and pretend it is a fact. Two of the nine are thin, and each
  says what would change its label.

The line is the label, a full stop, and then prose: `**Backing:** sourced. The mechanism is
this project's…`. A hedge lives in the prose, never in the label — a test reads the word
before the stop and nothing after it.

A principle marked *thin* is not a principle to skip. It is one to argue with.

## How to read a source row

`| S<n> | what it is | published | read | URL | cited for | notes |`

- **published** is the month the source carries on its own page, or `living` for a
  maintained reference page that carries no date. A date computed by a fetch tool from a
  timestamp was checked against the page before it went in.
- **read** is the month the source was last opened by whoever edited the row.
- **notes** says `older` when the source was published more than two months before it was
  read. The field this project sits in changes month to month — the same tool can change its
  storage engine and ship a major version between two citations — so an undated source can
  recommend a practice the ecosystem has already left. Older sources are cited for what they
  established, and a fresh source is named beside them where the claim is still current.
  A test checks that the label is present wherever the arithmetic says it must be, and
  absent where it must not; it does not fetch anything.
- A row whose URL could not be fetched when it was added says so in **notes** and names the
  secondary source the URL came from. Nothing is cited from memory.

## Where the word "harness" comes from

Anthropic wrote about harnesses for long-running agents in November 2025 [S27], OpenAI
described "harness engineering" as a discipline in February 2026 [S28] and open-sourced its
own agent harness in August 2026 [S30], and Lilian Weng generalised the term to
self-improvement loops in July 2026 [S29]. In all four the harness is what surrounds the
model: the tools, the context, the guards, the memory. drybag uses the word the same way,
and narrows it to the part of the harness that encodes *how a particular person works* —
which is the part none of those four covers, and the part that does not travel between
machines unless something carries it.

The code draws a line of its own. The private layer — the note store and its sync, the private
overlay, the binding of a repository to that overlay, a machine's setup and the session hints — is
the **delivery** side, the documentation and commit checks are the other side, and the **core** is
what both import ([CONTRIBUTING.md](../../CONTRIBUTING.md#areas) says how that is held). The
code also uses the word in a narrower sense of its own: there, a harness is the agent a session
runs in, Claude Code or Codex, one value each in a registry that the README's table of what each
agent enforces is held equal to.

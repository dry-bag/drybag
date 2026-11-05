# Asking across harnesses

The questions come from `stayfixed init --questions --json`: each property under
`questions.properties` is one question, asked in the order `questions.required` lists them (the
properties themselves arrive sorted by name); its `oneOf`, `items.enum` or `boolean` type gives
its options, and its `default` is the recommendation, offered first and marked so.
`project.name` and `project.base_branch` are free text held to the property's `pattern`, and so is
each commit type; the command refuses a value outside it, naming the rule.
Each question's `x-stayfixed-tradeoff` is four lines, relayed as written with the question:
what you get, what you give up, what it leaves behind, how to undo it.

| Step | Up to 4 questions of up to 4 options, multi-select | Up to 3 questions of 2–3 options, no multi-select | No ask tool |
|---|---|---|---|
| 2, take every default | one question | one question | one plain question |
| 3, the name and the base branch | one confirm question | one confirm question | one plain question |
| 3, corrections | the named values, in one call | the named values, in one call | one per turn |
| 4, each remaining question | one question per call, its four lines in the question | the same | one per turn |
| 4, the overlay follow-up | a call of its own | a call of its own | one turn |
| 4, a list (the plugins) | one multi-select question per four options | one free-text question listing the options, answered comma-separated | one question listing the options |
| 5, the final yes | one question | one question | one plain question |

- **Free text.** A name, a branch or a commit type is a plain question, or the default plus the
  harness's own free-text answer where it has one.
- **The overlay follow-up depends on the answer before it,** so it never shares that call.
- **Every option list stays within the limit.** A longer list is split across questions,
  never cut.
- **Silence is not consent.** A timeout, an empty answer, or "continue with your best judgment"
  never counts as a yes to write anything.

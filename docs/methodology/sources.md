# Sources

The citation pack for [principles.md](principles.md); how to read a row is in
[README.md](README.md).

| Id | Source | Published | Read | URL | Cited for | Notes |
|---|---|---|---|---|---|---|
| S1 | Claude Code docs: Create plugins | living | 2026-09 | https://code.claude.com/docs/en/plugins | the plugin as the unit of delivery; plugin-owned skills, agents and hooks | |
| S2 | Claude Code docs: Plugins reference | living | 2026-09 | https://code.claude.com/docs/en/plugins-reference | `${CLAUDE_PLUGIN_ROOT}` and `${CLAUDE_PLUGIN_DATA}`; `plugin.json`'s `version` as what pins update delivery | |
| S3 | Claude Code docs: Hooks reference | living | 2026-09 | https://code.claude.com/docs/en/hooks | per-event exit-code semantics; the 10,000-character cap on each hook's output; `env` blocks in a committed settings file | the cap is stated verbatim on the page; a summarising fetch missed it twice and a raw read found it |
| S5 | Claude Code docs: Memory | living | 2026-09 | https://code.claude.com/docs/en/memory | auto-memory as Markdown notes with a `MEMORY.md` index; the first 200 lines or 25 KB of the index loaded per session | |
| S6 | Claude Code docs: Plugin marketplaces | living | 2026-09 | https://code.claude.com/docs/en/plugin-marketplaces | private marketplaces; a marketplace entry's version is overridden by the plugin's own | |
| S7 | Codex docs: Hooks | living | 2026-09 | https://learn.chatgpt.com/docs/hooks | `hooks/hooks.json` read by both harnesses; `PLUGIN_ROOT` mirrored as `CLAUDE_PLUGIN_ROOT`; the hook-trust hash; async hooks cannot block | the developers.openai.com address redirects here permanently |
| S8 | Codex docs: Build a plugin | living | 2026-09 | https://developers.openai.com/codex/plugins/build | the Codex plugin manifest and its publishing validator | |
| S9 | openai/codex repository | living | 2026-09 | https://github.com/openai/codex | the discovery code that exports the plugin root under both names | Apache-2.0 |
| S10 | obra/superpowers v6.3.0 | 2026-08 | 2026-09 | https://github.com/obra/superpowers/releases/tag/v6.3.0 | the process-skills layer drybag delegates to and does not replace; the plan-location preference override | |
| S11 | github/spec-kit v1.0.7 | 2026-09 | 2026-09 | https://github.com/github/spec-kit/releases/tag/v1.0.7 | the manifest-with-hashes upgrade mechanism; a constitution declared up front, as the contrast to earned enforcement | |
| S12 | towncrier 26.9.0 | 2026-09 | 2026-09 | https://towncrier.readthedocs.io/ | changelog fragments assembled at release | |
| S13 | uv releases | 2026-09 | 2026-09 | https://github.com/astral-sh/uv/releases | `uv tool install` from a git tag; a stdlib-only tool needs no resolver at hook time | the docs site's footer date is stale; the release page carries the version |
| S15 | Agent Plugins 1.0.0 | 2026-08 | 2026-09 | https://agent-plugins.org/specification | a plugin with a declared dependency and its own manifest as a portable unit — the shape the overlay takes | |
| S16 | W3C AI Agent Memory Interoperability Community Group | 2026-06 | 2026-09 | https://www.w3.org/community/ai-agent-memory-interop/ | that there is no standard for coding-agent memory yet: the group works at protocol level and is not standards-track | older; charter adopted 2026-06-19 |
| S17 | Anthropic, "Effective context engineering for AI agents" | 2025-09 | 2026-09 | https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents | context as a budget; just-in-time retrieval over pre-loading; the cost of every token that arrives unasked | older |
| S18 | A-MEM: Agentic Memory for LLM Agents (NeurIPS 2025) | 2025-02 | 2026-09 | https://arxiv.org/abs/2502.12110 | linked notes with generated descriptions as a memory structure, the closest published shape to a routing-line index | older; background, not a design input |
| S19 | Mem0 | 2025-04 | 2026-09 | https://arxiv.org/abs/2504.19413 | the alternative drybag does not take: a second store with its own index | older; background |
| S20 | τ-bench | 2024-06 | 2026-09 | https://arxiv.org/abs/2406.12045 | pass^k: a behaviour that passes once is not a behaviour that passes | older |
| S21 | "Stochasticity in Agentic Evaluations: Quantifying Inconsistency with Intraclass Correlation" | 2025-12 | 2026-09 | https://arxiv.org/abs/2512.06710 | run-to-run inconsistency of agent evaluations, measured | older |
| S22 | OWASP Top 10 for LLM Applications 2026 | 2026-08 | 2026-09 | https://genai.owasp.org/resource/owasp-genai-llm-top-10-2026/ | prompt injection and supply-chain entries as the threat classes a committed configuration reaches | the `/llm-top-10/` page still serves the 2025 edition |
| S23 | VibeCheck (arXiv 2609.05978) | 2026-09 | 2026-09 | https://arxiv.org/abs/2609.05978 | generated tests that "frequently lack strong assertions"; tautological tests | |
| S24 | "On the risk of coding before testing" (arXiv 2607.05139) | 2026-07 | 2026-09 | https://arxiv.org/abs/2607.05139 | implementations and tests that are mutually consistent and wrong together | |
| S25 | GitHub Docs: Reuse workflows | living | 2026-09 | https://docs.github.com/en/actions/how-tos/sharing-automations/reuse-workflows | "using the commit SHA is the safest option for stability and security" for a reusable workflow reference | |
| S26 | GitHub changelog: secret scanning and public monitoring | 2026-07 | 2026-09 | https://github.blog/changelog/2026-07-15-improvements-to-secret-scanning-and-public-monitoring/ | what secret scanning covers on a private repository, as of the date | |
| S27 | Anthropic, "Effective harnesses for long-running agents" | 2025-11 | 2026-09 | https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents | the harness as what surrounds the model over a long task | older |
| S28 | OpenAI, "Harness engineering: leveraging Codex in an agent-first world" | 2026-02 | 2026-09 | https://openai.com/index/harness-engineering/ | harness engineering named as a discipline | older; not fetched directly (the page refuses automated readers); URL and date from two secondary sources of 2026-02 |
| S29 | Lilian Weng, "Harness Engineering for Self-Improvement" | 2026-07 | 2026-09 | https://lilianweng.github.io/posts/2026-07-04-harness/ | the term generalised to self-improvement loops | |
| S30 | OpenAI, "Codex as a platform: build on the open agent harness" | 2026-08 | 2026-09 | https://developers.openai.com/blog/codex-as-a-platform | the Codex harness open-sourced | |
| S31 | Anthropic, "Building effective agents" | 2024-12 | 2026-09 | https://www.anthropic.com/engineering/building-effective-agents | the case for simple, composable patterns over frameworks | older; foundational |
| S32 | GitHub Docs: About secret scanning | living | 2026-09 | https://docs.github.com/en/code-security/secret-scanning/introduction/about-secret-scanning | availability of secret scanning per repository visibility and plan | |
| S33 | ESLint docs: Bulk suppressions | living | 2026-09 | https://eslint.org/docs/latest/use/suppressions | a linter that fails new violations while suppressing the ones already there: the hold-the-line step principle 7 records as next | |

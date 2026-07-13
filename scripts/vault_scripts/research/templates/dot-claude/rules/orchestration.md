# Agent Orchestration Rules

Apply whenever spawning research agents or workflows for this topic.

## Reliability (most orchestration failures are plumbing rather than model failures)

1. **Fail fast on inputs:** workflow scripts validate their data shape and throw a named error before any agent spawns.
2. **Embed datasets in the script;** reserve `args` for parameters of saved workflows.
3. **Compile, then execute:** build all prompts as pure code and log counts before spawning; shape bugs must cost milliseconds rather than agent tokens.
4. **Side-effects only at the end, in one place:** agents read and return; only the main loop writes the `data/` CSVs, after adjudication, so reruns are idempotent.
5. **Recover via resume** (`scriptPath` + `resumeFromRunId`) instead of resending; record workflow run IDs in the HANDOFF changelog.

## Token efficiency

- **Tier models to the work by capability, not by name:** finders and the critic run on a solid mid-tier model; purely mechanical checks (URL liveness, date extraction) on the cheapest capable model; the main-loop model only adjudicates and synthesizes. Don't tier the critic below the finders it judges. (Pick the current models that fit those tiers rather than hardcoding a name that ages out.)
- **Search budgets:** FINDER-PROMPT.md caps finders at ~15 search/fetch calls with a stop-at-target rule; finders read HANDOFF sourcing notes before searching.
- **Match the harness to the batch:** ~5 units per pass = plain parallel agents; orchestrated workflows only for large fan-outs (retro audits, full-log sweeps), with a stated token target.

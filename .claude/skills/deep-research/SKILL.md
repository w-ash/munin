---
name: deep-research
description: Deep research with vault-aware output placement. Default mode wraps the built-in deep-research workflow; scored mode runs our own durable workflow with mechanical citation checks, deterministic claim scoring, and rubric-based ranking of options. Lands the report in the vault per the trackers framework. Use when the user wants a deep, multi-source, fact-checked research report or a scored comparison of candidates. If the question is underspecified, ask 2-3 clarifying questions before running.
user_invocable: true
---

# Deep research (vault-aware)

This project skill intentionally shadows the built-in `deep-research` skill: the
research mechanics are unchanged, the output handling is vault-specific. If both
sets of instructions load, these win.

Refine the question first, either mode: if it is underspecified (missing scope,
region, budget, use case), ask 2-3 clarifying questions and weave the answers in.
State the recency rule inside the question when currency matters ("claims about
current practice need sources from the last year").

## Two modes

- **Default mode** (built-in workflow): quick, multi-source fact-finding. Fastest;
  use it for most questions.
- **Scored / durable mode** (our own workflow): use when the answer needs numeric
  grounding ("how certain are we"), a ranking of options against the user's
  priorities, a large fan-out, or resilience over a long run. The built-in
  workflow's agents are a black box we cannot checkpoint, score inside, or
  mechanically citation-check, which is why scored mode runs a custom workflow.

## Default mode

Invoke the built-in workflow: `Workflow({name: "deep-research", args: "<refined question>"})`.
It runs in the background; you get notified on completion. Read the full result
from the task output file if the notification truncates it.

## Scored / durable mode

Run the workflow at `templates/scored-research.js`:

    Workflow({ scriptPath: "<skill dir>/templates/scored-research.js",
      args: { question: "<refined>", runDir: "<run dir>",
              vaultTool: "<vault root>/scripts/vault-tool",
              rubric: <rubric object, ranking questions only>,
              recency: "<recency rule, optional>" } })

- `runDir`: deterministic and outside iCloud: `${TMPDIR}scored-research/<question-slug>`
  (slug from the question, no date, so a retry lands in the same directory).
  Before launching, check for `<runDir>/manifest.json`; if it exists a prior run
  does too, so resume it (below) instead of starting fresh.
- `vaultTool`: absolute path to the vault's `scripts/vault-tool`. Required; the
  workflow has no default.
- After launch, write the returned runId to `<runDir>/run.json` so a later resume
  can find it.

### Claim questions vs ranking questions

- Claim questions (is X true, what is the state of Y): omit `rubric`.
- Ranking questions (which of N options fits best): pass `rubric`, elicited in
  conversation BEFORE launching; the workflow never pauses for input.
  1. Agree on the candidates. If they need discovering first, run a default-mode
     pass to find them, then rank.
  2. Turn the user's stated priorities into criteria: kebab-case `id`, one-line
     `text`, `weight`, and `tier` (`blocker` disqualifies when failed; `must` is
     load-bearing; `should`; `nice`).
  3. Show the rubric as a table and get sign-off, then launch with
     `rubric: {criteria, candidates: [{id, name}], blocker_threshold}`.

  Grid claim ids (`<candidate>--<criterion>`) are built by the workflow; never
  hand-write them.

### What a run does

Scope (facets, a centrally diversified query pool per facet, claim registry,
manifest) -> Find (one finder per facet, validated append-as-you-go, extra
coverage rounds while facets stay unsaturated and budget allows) -> Citations
(`evidence verify-citations` fetches every cited URL and mechanically checks the
quote is there, Wayback fallback included; `evidence check` reconciles shard
claim ids against the manifest) -> Verify (fresh-context refuter subagents on
the load-bearing claims only) -> Score (`evidence score`, plus `evidence rank`
in ranking mode; every number comes from the deterministic engine) -> Refine
(one targeted re-research round for low-confidence load-bearing claims, then
recheck and rescore) -> Synthesize (cited report; ranking mode adds a
swap-order pairwise sanity check on the top two candidates, with disagreement
reported rather than averaged). Full mechanics in `.claude/rules/evidence.md`.

### Durability and resume

- Each finding is recorded the moment it is confirmed via `vault-tool evidence
  append` (validated; a bad item fails loudly at write time), so a wall or
  disconnect costs one in-flight item, not the run.
- Same session: `Workflow({ scriptPath, resumeFromRunId: "<from run.json>" })`.
  Completed agents replay from cache; the shards persist regardless.
- Across sessions the agent cache is gone but the shards are not: relaunch with
  the same `runDir`. Re-found evidence deduplicates at merge time and the
  citation pass reuses its HTTP cache, so a rerun converges instead of
  double-counting.
- Shards, `manifest.json`, `citations.jsonl`, and `.http-cache/` are disposable
  run artifacts; never copy them into the vault.

### Cost posture

A scored run spends roughly 20 to 40 agents. A token budget in the user's
message (the "+300k" form) scales coverage: extra find rounds, more verifiers,
and the refine pass all gate on remaining budget, and the workflow logs
whatever coverage it drops so nothing is silently skipped.

## Output placement (trackers framework)

The cited report is a notes-as-record artifact (`.claude/rules/trackers.md`):
one markdown note, placed where the requesting context dictates:

- Research feeding a project decision: the project's folder, or `Meta/` when the
  subject is vault structure or conventions themselves.
- Trip research: the trip's folder (`Travel/<Trip>/References/` when it exists).
- Freestanding exploration: `Ideas/`.

Note requirements:

- `created: "YYYY-MM-DD"` frontmatter; follow the destination folder's tag
  conventions (e.g. `meta` in `Meta/`).
- Structure: a one-paragraph headline verdict; findings grouped by confidence
  band, each stating its certainty and citing its sources; a refuted /
  low-confidence section (what verification drove down); caveats; open questions;
  and a sources list. In scored mode the certainty numbers and bands come from
  `vault-tool evidence score`; keep the refuted section, it is decision input, not
  noise.
- Prose per `.claude/rules/writing.md` (plain punctuation, no em dashes).
- Wikilink the report from the note that prompted the research, and link back.

The workflow's raw JSON result is disposable (trackers tier rule: the note is
the record; the run artifact lives in tmp and dies with the session). Never
copy raw agent transcripts into the vault.

## Deliver

End with a chat summary that answers the user's actual question and links the
note. The note is the record; the chat message is the projection.

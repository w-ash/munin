---
name: deep-research
description: Deep research with vault-aware output placement. Wraps the built-in deep-research workflow (fan-out searches, source fetching, adversarial claim verification, cited synthesis) and lands the report in the vault per the trackers framework. Use when the user wants a deep, multi-source, fact-checked research report. If the question is underspecified, ask 2-3 clarifying questions before running.
user_invocable: true
---

# Deep research (vault-aware)

This project skill intentionally shadows the built-in `deep-research` skill: the
research mechanics are unchanged, the output handling is vault-specific. If both
sets of instructions load, these win.

## Run

1. Refine the question first. If it is underspecified (missing scope, region,
   budget, use case), ask 2-3 clarifying questions and weave the answers in.
   State the recency rule inside the question when currency matters ("claims
   about current practice need sources from the last year").
2. Invoke the built-in workflow: `Workflow({name: "deep-research", args: "<refined question>"})`.
   It runs in the background; you get notified on completion. Read the full
   result from the task output file if the notification truncates it.

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
- Structure: a one-paragraph headline verdict, findings with confidence levels
  and source links, refuted claims (what verification killed), caveats, open
  questions, and a sources list. Keep the refuted section: it is decision
  input, not noise.
- Prose per `.claude/rules/writing.md` (plain punctuation, no em dashes).
- Wikilink the report from the note that prompted the research, and link back.

The workflow's raw JSON result is disposable (trackers tier rule: the note is
the record; the run artifact lives in tmp and dies with the session). Never
copy raw agent transcripts into the vault.

## Deliver

End with a chat summary that answers the user's actual question and links the
note. The note is the record; the chat message is the projection.

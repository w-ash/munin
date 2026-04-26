---
description: Rules for daily journal entries in the Daily/ folder
globs: Daily/**
---

# Daily Journal Conventions

## File naming
`YYYY-MM-DD.md` — one file per day

## Required frontmatter
created: YYYY-MM-DD
date: YYYY-MM-DD
tags:
  - daily

## Structure
Use the Daily Journal template. Sections are optional — write what's relevant, skip what isn't. The goal is low-friction capture, not completeness.

## Voice attribution

Every entry has two zones, separated by the `---` divider in the template.

### Zone 1 — Ash's voice (top, default)

Everything above the divider is Ash's. Whether typed directly in Obsidian or captured verbatim from chat dictation, his words go into the natural sections (`What happened today`, `How I'm feeling`, `What I want`) as **plain prose**. No callouts. No injected wikilinks. No typo or grammar fixes. The voice is the point.

### Zone 2 — Claude's synthesis (bottom — `Links & Connections`)

Everything Claude adds — wikilinks, structured summaries, related-note pointers — consolidates in the `## Links & Connections` section below the `---`. The HTML comment (`<!-- Added by Claude — wikilinks, backlinks, related notes -->`) is the **machine-readable provenance marker** — keep it on every entry that has synthesis. The section header is the human-readable marker.

Default format is index-style:

```markdown
## Links & Connections
<!-- Added by Claude — wikilinks, backlinks, related notes -->

**People**: [[Person A]] · [[Person B]] · [[Person C|Nickname]]
**Event**: [[Event]] context
**Context**: relationships or background that ties the entry to other notes
```

A short prose summary is fine when it adds context the wikilinks can't carry — but don't pad.

### Rules of capture

<important>
1. **Never edit Ash's prose** — no wikilinks injected, no typo fixes, no rephrasing.
2. **All synthesis lives below the `---`** in `## Links & Connections`.
3. **Verbatim is verbatim** — preserve casing, typos, asides, all of it.
4. **Drop the capture** if Ash says "this is just for you" or "don't log this."
5. **One consolidated synthesis block** per entry. Update it in place as the entry grows; don't append new blocks.
6. **Synthesis is index-style by default.** Prose summaries only when they add context wikilinks can't carry.
7. **Keep the `<!-- Added by Claude … -->` HTML comment.** It's the machine-readable provenance marker; future scripts grep for it.
</important>

This pattern aligns with 2026 PKM and AI-provenance norms (explicit, section-level attribution beats inline markup or detection-based approaches).

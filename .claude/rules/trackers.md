---
description: Storage framework for life-tracking domains, covering tier assignment and shared tracker-note conventions
paths:
  - "Meta/**"
  - "Projects/**"
  - "Ideas/**"
  - "Movies/**"
  - "Concerts/**"
  - "Weekends/**"
  - "Health/**"
  - "People/**"
  - "Restaurants/**"
  - "Shops/**"
  - "Pets/**"
---

# Trackers

How the vault stores life-tracking data. Rationale, per-domain map, and migration
playbook live in `Meta/Trackers.md`; this file is the operative summary.

**When this rule applies:** spinning up a new project, adding a tracked domain, or
deciding where any data should be saved. Assign the data a tier with the rule below
before creating folders or files.

## Two tiers, one rule

Every tracked domain has exactly one location of truth. Everything else about it is a
regenerable projection.

- **Notes-as-record.** Records arrive at human pace (tens to low hundreds a year) and
  each is worth opening to annotate. The markdown note IS the canonical record. Folder
  shape: `Domain/entries/*.md` + `Domain/<Name>.base`, tag-filtered.
- **Canonical-files.** Records are machine-generated at volume (high hundreds to
  thousands a year) and no individual record gets hand-written commentary. Append-only
  plain-text layers (JSONL; CSV for flat shapes) under the owning folder (e.g.
  `Health/data/`), markdown as projection only. The query layer is a materialized
  DuckDB cache outside iCloud, rebuilt with `vault-tool db rebuild` and queried with
  `vault-tool db query`: disposable, never the record. Agents reach telemetry through
  that tool, not raw file reads.

A small third kind sits beside these two: **reference data**, slowly-changing lookup
tables that are neither event records nor annotated notes (e.g. the supplement
substance registry, `Health/data/reference/substances.jsonl`: canonical nutrients,
units, upper limits). Kept as JSONL under `Health/data/reference/` so the same DuckDB
cache reads it with no extra code, hand-maintained and edited in place, git-versioned.
Reach for it only when a domain genuinely needs a shared lookup table; a handful of
rows do not warrant a note apiece.

Default a new domain to notes-as-record; demote to canonical-files only when volume
actually hurts. Mixed domains split at the same line (a sickness episode is a note;
its temperature series is telemetry) and wikilink across. A domain that can't be
captured lazily gets deferred, not tooled: no new capture chores.

## Tracker-note conventions

- Core frontmatter: `created: "YYYY-MM-DD"`, one domain tag, `status` where a
  lifecycle exists, bare dates for date fields (`date`, `last_<verb>`).
- Editing frontmatter: one note → the Edit tool (exact-string, preserves quoting);
  many notes → `vault-tool fm set <path…> key=value [key:int=N] [--after F] [--write]`
  (dry-run by default). Never `obsidian property:set` for writes: it reserializes the
  whole block and unquotes `created`, `coordinates`, and every other string field.
- New domains use `snake_case` property names. Restaurants keeps its existing
  kebab-case fields; no retrofits.
- Imported records carry provenance, and importers match on it before creating
  anything, so re-imports are no-ops:

  ```yaml
  source: ""     # letterboxd | airtable | gsheet | ...  (omit for manual notes)
  source_id: ""  # stable per-record key in that source
  ```

- Dated log sections (`## Visits`, `## Watches`, `## Contact log`), one line per
  event:

  ```markdown
  - **[[YYYY-MM-DD]]** — who ([[wikilinks]]), what, how it was.
  ```

  The date wikilink into `Daily/` is the join key between trackers and the journal.
  Keep a matching `last_<verb>` frontmatter field in sync for base sorting.
- Machine data reaches daily notes only as projections: frontmatter properties and
  script-owned sentinel blocks (see `daily.md`). Never in Ash's prose zones.
- Each shipped domain documents its schema in `.claude/rules/<domain>.md`.

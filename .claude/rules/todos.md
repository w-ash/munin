---
description: Rules for working with weekly todo files in the Todos/ folder
globs: Todos/**
---

# Todo Conventions

## Weekly file structure

One file per week in `Todos/`, created from the "Weekly Todo" template. Sections are **category-based** (not day-of-week):

- **Carry-over** — query pulling incomplete items from prior weeks
- **Routines** — query pulling recurring items from `Routines.md`
- **Inbox** — landing zone for new tasks
- **Home & Household** — chores, errands, repairs, pet care
- **Health** — appointments, fitness, mental health
- **Finance** — bills, taxes, budgeting
- **People & Social** — plans with friends, family, events
- **Projects** — active personal project tasks (link to `Projects/`)
- **Travel** — trip planning tasks
- **Career** — job search, portfolio, networking
- **Later** — low priority this week, still time-bound
- **Next Week** — tasks for the following week

Empty sections are fine; delete unused ones from individual weeks if distracting.

## Checkbox statuses

- `- [ ]` — open
- `- [x]` — done (Tasks plugin auto-stamps `✅ YYYY-MM-DD`)
- `- [>]` — forwarded to another week
- `- [-]` — cancelled / won't do; add a reason if helpful: `- [-] Task (won't do — no longer relevant)`

## Adding tasks

New tasks go to **Inbox** unless the user specifies a category. Ask a clarifying question before writing ambiguous or vague tasks — every todo must be clear enough to act on days/weeks later.

## Moving tasks between weeks

1. In the old file: change `- [ ]` to `- [>]` (forwarded). **Don't delete the line.**
2. In the new file: add as `- [ ]` under Inbox (or the appropriate category).

## Dates, recurrence, priority, links

Obsidian Tasks plugin syntax, inline at the end of the task line:

- Due date: `📅 2026-04-10`
- Recurring: `🔁 every week on Tuesday` (lives in `Todos/Routines.md`, surfaces via Tasks query; completion auto-creates the next occurrence)
- Priority: `🔺` highest · `⏫` high · `🔼` medium · `🔽` low
- Supporting doc: `[[Supporting Doc]]`

## Backlog vs Later

- **Later** (in weekly files) = low priority this week, still time-bound
- **Backlog** (`Todos/Backlog.md`) = no specific timeframe, someday/maybe

---
name: triage
description: Walk through incomplete todos across the vault and triage them one at a time
user_invocable: true
---

# Todo Triage

Triage incomplete todos across the vault. Search for open tasks, present them one at a time, and help the user decide what to do with each.

## Steps

1. **Find the current week's todo file** — run `obsidian files folder="Todos"` to list files, then check each for a `week_start` property that covers today's date. If none exists, ask the user if they'd like to create one from the "Weekly Todo" template before proceeding.

2. **Search for open todos** — run `obsidian tasks todo verbose format=json` to find all open tasks. Exclude results from:
   - The current week's todo file
   - `Todos/Routines.md`
   - `Todos/Backlog.md`
   - Any file in `Templates/`
   - Any file in `Archive/`
   - Any file in `.claude/`
   - Setup/reference docs (CLAUDE.md, rules files, skill files)

3. **Group by file, most recent first.**

4. **Present one todo at a time** — show the task text, source file, and line number. Ask what to do:
   - **Move** → forward to current week's todo file (Inbox section)
   - **Done** → mark complete
   - **Cancel** → mark cancelled with optional reason
   - **Backlog** → move to Backlog.md
   - **Skip** → leave as-is for now

5. **Apply the chosen action:**
   - Move → `obsidian task path="file.md" line=N status=">"` in old file, then append to the **Inbox** section of the current week's file
   - Done → `obsidian task path="file.md" line=N done`
   - Cancel → `obsidian task path="file.md" line=N status="-"`
   - Backlog → `obsidian task path="file.md" line=N status=">"`, then `obsidian append file="Backlog" content="- [ ] task text"`
   - Clarify ambiguous items before moving — if a task is too vague to act on, ask what it means first

6. **Summarize** what was moved, completed, cancelled, and sent to backlog when done.

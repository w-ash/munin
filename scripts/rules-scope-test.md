# Rules scoping test

A self-checking probe for instruction scoping. Run it twice, each time in a
FRESH session (no prior conversation), from these two launch directories:

1. `~/Projects/munin` (the tooling repo)
2. the Aesc vault root in iCloud (where `.claude`, `CLAUDE.md`, and `scripts`
   are symlinks into munin)

Launch from the root of each, not a subdirectory. In each session say:
"read scripts/rules-scope-test.md and follow it".

Delete this file once both contexts pass.

## Instructions for Claude

You have just read this file, which lives under `scripts/`, so the path-scoped
vault-scripts rule should have been injected by that read. Before reading
anything else, evaluate the table below against what is ACTUALLY in your
context right now: startup instructions plus any rule text injected so far.
Identify items by topic; do not use this file's wording as evidence, and do not
guess from filenames. If you cannot see it, it is ABSENT.

| # | Item (by topic) | Expect from munin | Expect from Aesc |
|---|---|---|---|
| 1 | Vault project instructions (vault folder structure, Obsidian CLI usage, a numbered rules block) | PRESENT | PRESENT |
| 2 | Writing-style rule (plain punctuation, a list of banned words) | PRESENT | PRESENT |
| 3 | User-global rules on git conventions, working style, or investigation discipline | ABSENT | ABSENT (the user rules dir is empty; git conventions now live in a user-level skill, tested in step D) |
| 4 | Vault-scripts standards (a strict type-checker held at zero errors, a bash dispatcher, typed argparse) injected when you read this file | PRESENT | PRESENT |
| 5 | Food and diet preferences for Ash and Kew | ABSENT | ABSENT so far (loads later, in step B) |
| 6 | A standing job or numbered task list about auditing two vaults for consistency | ABSENT | ABSENT (a short factual note that two vaults exist and a pointer to a skill is a PASS; an assigned "your job" task list is a FAIL) |
| 7 | Schema rules for travel, dining, people, or daily notes | ABSENT | ABSENT (they load only when matching files are read) |

## Follow-up steps

- Step A (both contexts): read any `.py` file under `scripts/vault_scripts/`,
  then check that a Python tooling rule (uv, a preferred Python version)
  injected.
- Step B (Aesc only): read any note under `Restaurants/entries/`, then check
  that the food and diet preferences rule injected. This is the key test that
  the diet rule moved correctly from user-global to path-scoped.
- Step C (Aesc only): read any note under `Travel/`, then check that travel
  planning and geo rules injected.
- Step D (both contexts): check that a `git-conventions` skill (terse
  conventional-commit subjects, commit batching) appears in your available
  skills, and that you would load it before composing a commit message. Do not
  actually commit anything.

## Reporting

Print a table: item number, PRESENT or ABSENT, PASS or FAIL against the
expectation column for your launch directory, including rows for steps A-C.
Finish with one line: OVERALL PASS or OVERALL FAIL, plus which items failed.

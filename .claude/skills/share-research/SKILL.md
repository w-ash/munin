---
name: share-research
description: Push a research topic's evidence store and computed columns to its Google Sheet mirror (one-way). Use when asked to sync, push, publish, or share research results to a Sheet.
user_invocable: true
argument-hint: "[--dry-run] [--force]"
---

# Share Research to Google Sheets

Push the topic's `data/` CSVs plus the mode's computed columns to the Google Sheet named in `research.toml`. One-way: the CSVs are the source of truth, and each push rewrites every tab in place, so treat the Sheet as read-only.

## Prerequisites

- `research.toml` has `[sheets] sheet_id` set (the Sheet must already exist; the tool never creates it; the id comes from the URL `/spreadsheets/d/<id>/`).
- `[sheets] auth` picks the identity: `oauth` (default, acts as you and needs no sharing) or `service` (the shared service account; share the Sheet with its `client_email` as Editor).
- Auth uses the vault's Google stack, the same one behind `scripts/vault-tool sheets` and `docs`: OAuth-user needs the one-time `scripts/vault-tool docs auth-login`; both modes read their credentials from the dispatcher's `.env` (`GOOGLE_OAUTH_CLIENT_JSON` / `GOOGLE_OAUTH_TOKEN_JSON`, `GOOGLE_SHEETS_SA_JSON`). See `.claude/skills/google-sheets/` for the auth modes and setup.

## Run

From the topic directory (or with `--dir`):

```bash
scripts/vault-tool research sync $ARGUMENTS
```

`--dry-run` reports the planned tabs without writing; `--force` pushes even when the content hash says nothing changed.

## Report

Read the JSON envelope and report: `status` (synced / skipped / dry-run), the Sheet `url`, the identity used, and per-tab row counts. On `skipped`, say the store is unchanged and mention `--force`. On an error envelope, surface the message; the common causes are a wrong sheet id, a Sheet not shared with the service account, or missing OAuth credentials.

## Notes

- The mode's core tab carries its computed block (map: confidence columns on Taxonomy; verify: certainty on Claims; rank: fit on Candidates; find: coverage rates on Attributes; estimate: mu/sigma/variance_share on Factors), and a per-mode model doc tab ("Confidence model" / "Certainty model" / "Fit model" / "Coverage model" / "Estimate model") documents the math with the topic's actual parameters.
- Validation runs first: a store with `research check` errors won't push.
- The skip-state cache is a disposable `.research-sync-state.json` inside the topic directory; delete it (or pass `--force`) to re-push unchanged content.

---
name: google-docs
description: Read and edit Google Docs from the vault toolchain via `scripts/vault-tool docs`. Use when the user wants to export a Doc to Markdown, edit a Doc's text, fill a template, create a Doc from a note, or pastes a docs.google.com/document link. Reads and in-place edits go through a service account (share the doc with it first); creating new Docs needs the one-time OAuth login.
user_invocable: true
---

# Google Docs

Read and write Google Docs over the Docs and Drive REST APIs through the `docs`
module of the vault toolchain. Every command prints a JSON envelope and runs
read-only unless `--write` is passed. It shares its auth, retry, and transport
with `/google-sheets` (the `_google` seam).

## Access (do this first)

In `--auth service` mode (the default) the tool authenticates as a service
account, not as Ash. A doc is reachable only once it has been shared with that
account; otherwise every call returns 403. Share the doc (or its parent folder)
with this address, **Editor** to write, **Viewer** to read only:

```
vault-sheets@vault-492101.iam.gserviceaccount.com
```

A call that exits with code 4 (permission) means the doc isn't shared yet. Ask
Ash to share it with that address.

## Auth modes

- `--auth service` (default): the service account. Reads and in-place edits of
  shared docs. Cannot create or own files.
- `--auth oauth`: acts as Ash, so it can own files. Needed for `create` and
  `template`. Run the one-time consent first:

```bash
scripts/vault-tool docs auth-login
```

This opens a browser, asks Ash to approve, and stores a refresh token at
`~/.config/gcp/docs-oauth.json`. After that, `--auth oauth` runs unattended.

## Read commands

The document argument takes a bare ID or a full Docs URL.

```bash
# Export the doc to Markdown (one Drive call, no index math). Prints the Markdown.
scripts/vault-tool docs export <id|url>

# Export straight to a vault file
scripts/vault-tool docs export <id> --out "Work/Notes/spec.md"

# Body as a {start, end, text} index map plus title/revisionId/endIndex —
# the practical way to find an index for insert/delete/style
scripts/vault-tool docs get <id>

# The full raw documents.get JSON (the structural escape hatch)
scripts/vault-tool docs get <id> --raw-json

# Title, revisionId, end index, named-range count
scripts/vault-tool docs info <id>

# Find Google Docs in Drive by name (paginates internally)
scripts/vault-tool docs find --query "Quarterly Spec"

# List the named ranges in a doc
scripts/vault-tool docs list-named-ranges <id>
```

`export` is the default read path: Drive's native Markdown export is one call and
far more token-efficient than the structural JSON. Reach for `get --raw-json` only
when you need exact indexes for surgical edits.

## In-place write commands

These edit a doc the service account can already reach. All default to a dry-run
and need `--write`. Indexes are UTF-16 code units; **every insert or delete shifts
later indexes**, so edit back to front when you stack edits, and prefer
`append-text` (no index) or `replace-all` (text match) when you can.

```bash
# Append to the end of the body (no index needed)
scripts/vault-tool docs append-text <id> --text "One more line." --write

# Insert at a specific index (from `get`)
scripts/vault-tool docs insert-text <id> --index 25 --text "Hi " --write

# Delete the content in [start, end)
scripts/vault-tool docs delete-range <id> --start 25 --end 30 --write

# Style a range (any of --bold/--no-bold, --italic, --underline, --link)
scripts/vault-tool docs style-text <id> --start 1 --end 12 --bold --link "https://x" --write

# Replace every occurrence of a string (the templating / mail-merge primitive)
scripts/vault-tool docs replace-all <id> --find "{{name}}" --replace "Ash" --write

# The long tail: a raw list of batchUpdate requests (tables, bullets, headers, ...)
scripts/vault-tool docs batch <id> --requests '[{"insertTable":{"rows":2,"columns":2,"endOfSegmentLocation":{}}}]' --write
```

### Safe index-based edits

`insert-text`, `delete-range`, `style-text`, and `batch` take an optional
`--revision-id`. Read it from `get`/`info`, base your indexes on that same read,
and pass it back: the write is rejected (a clean error) if the doc changed since,
so your indexes can't land on shifted content.

```bash
scripts/vault-tool docs get <id>            # note "revisionId": "..."
scripts/vault-tool docs delete-range <id> --start 25 --end 30 --revision-id "<rev>" --write
```

## Creating docs (OAuth)

Owned-file creation can't run as the service account, so these need `--auth oauth`
(after `auth-login`). They default to a dry-run.

```bash
# Create a new Doc from a Markdown note (Drive's native importer)
scripts/vault-tool docs create --from "Work/Notes/spec.md" --title "Q3 Spec" --auth oauth --write

# Copy a template doc and fill its placeholders, then return the new doc
scripts/vault-tool docs template --template-id <id> --title "Offer — Ash" \
  --replace "{{name}}=Ash" --replace "{{city}}=Seattle" --auth oauth --write
```

`--replace FIND=VALUE` is repeatable; `FIND` is the literal text to match, so
include any `{{ }}` braces yourself.

## Markdown caveats

Native export and import cover headings, lists, bold/italic, links, and basic
tables, but don't round-trip everything: complex tables can lose column widths,
and images come through as base64 (which render broken) on import. For precision
beyond what Markdown carries, build the edit with `batch`. Drive's `export` caps at
10 MB (a clean `exportSizeLimitExceeded` error above that).

## Write safely

The mutating commands (`append-text`, `insert-text`, `delete-range`, `style-text`,
`replace-all`, `batch`, `create`, `template`) print what they *would* do under a
`dryRun` key and change nothing until `--write`. Run once without `--write`, show
Ash the preview, then re-run with `--write`. Writes hit a live, shared doc, so
confirm before applying.

## Output and exit codes

Each command prints `{ok, cmd, documentId, result}`. On failure it prints
`{ok: false, ..., error}` and exits non-zero:

- `2` — bad input (malformed JSON, missing argument, wrong auth mode for `create`)
- `3` — auth (the service-account key or OAuth token is missing or invalid)
- `4` — permission (the doc isn't shared with the service account)
- `5` — other API error

When Google returns a structured error body, the envelope also carries the parsed
`status` (e.g. `PERMISSION_DENIED`, `INVALID_ARGUMENT` for a stale
`--revision-id`) and `code`. The tool retries 429/5xx with backoff, honoring a
`Retry-After` header when present.

Credential storage and setup: `scripts/.env` (`GOOGLE_DOCS_SA_JSON`,
`GOOGLE_OAUTH_CLIENT_JSON`, `GOOGLE_OAUTH_TOKEN_JSON`) and `~/.config/gcp/README.md`.
